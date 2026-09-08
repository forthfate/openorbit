"""One disposable local PTY per connected browser terminal."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import subprocess
from pathlib import Path

from fastapi import WebSocket, WebSocketDisconnect

from .assistant_tools import normalize_settings


async def serve_terminal(websocket: WebSocket, configured: object) -> None:
    settings = normalize_settings(configured)
    root = Path(settings["workspace_root"]).resolve()
    if not settings["terminal_enabled"] or not settings["terminal_visible"] or not root.is_dir():
        await websocket.close(code=1008)
        return
    await websocket.accept()
    if os.name == "nt":
        await _serve_windows(websocket, root)
    else:
        await _serve_unix(websocket, root)


async def _serve_unix(websocket: WebSocket, root: Path) -> None:
    import fcntl
    import pty
    import struct
    import termios

    master, slave = pty.openpty()
    shell = os.environ.get("SHELL") or "/bin/sh"
    process = subprocess.Popen(
        [shell],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        cwd=root,
        start_new_session=True,
        close_fds=True,
        env={"PATH": os.environ.get("PATH", ""), "TERM": "xterm-256color"},
    )
    os.close(slave)

    async def output_loop() -> None:
        while True:
            data = await asyncio.to_thread(os.read, master, 4096)
            if not data:
                return
            await websocket.send_text(data.decode("utf-8", errors="replace"))

    async def input_loop() -> None:
        while True:
            message = json.loads(await websocket.receive_text())
            if message.get("type") == "input":
                os.write(master, str(message.get("data", "")).encode())
            elif message.get("type") == "resize":
                fcntl.ioctl(
                    master,
                    termios.TIOCSWINSZ,
                    struct.pack("HHHH", int(message.get("rows", 24)), int(message.get("cols", 80)), 0, 0),
                )

    try:
        output = asyncio.create_task(output_loop())
        receive = asyncio.create_task(input_loop())
        _, pending = await asyncio.wait({output, receive}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
    except (WebSocketDisconnect, OSError, json.JSONDecodeError):
        pass
    finally:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        os.close(master)


async def _serve_windows(websocket: WebSocket, root: Path) -> None:
    from winpty import PtyProcess

    shell = shutil.which("pwsh") or shutil.which("powershell") or "cmd.exe"
    process = PtyProcess.spawn(shell, cwd=str(root))

    async def output_loop() -> None:
        while True:
            output = await asyncio.to_thread(process.read, 4096)
            if not output:
                return
            await websocket.send_text(output)

    async def input_loop() -> None:
        while True:
            message = json.loads(await websocket.receive_text())
            if message.get("type") == "input":
                process.write(str(message.get("data", "")))
            elif message.get("type") == "resize":
                process.setwinsize(int(message.get("rows", 24)), int(message.get("cols", 80)))

    try:
        output = asyncio.create_task(output_loop())
        receive = asyncio.create_task(input_loop())
        _, pending = await asyncio.wait({output, receive}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
    except (WebSocketDisconnect, OSError, json.JSONDecodeError):
        pass
    finally:
        process.close()
