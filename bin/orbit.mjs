#!/usr/bin/env node
import { existsSync } from 'node:fs'
import net from 'node:net'
import { platform } from 'node:os'
import { join } from 'node:path'
import { spawn, spawnSync } from 'node:child_process'

const root = new URL('..', import.meta.url).pathname
const python = platform() === 'win32' ? 'py' : 'python3.13'
const pythonVersionArgs = platform() === 'win32' ? ['-3.13'] : []
const venvPython = platform() === 'win32' ? join(root, '.venv', 'Scripts', 'python.exe') : join(root, '.venv', 'bin', 'python')

function run(command, args) {
  const result = spawnSync(command, args, { cwd: root, stdio: 'inherit' })
  if (result.status !== 0) process.exit(result.status ?? 1)
}

function availablePort(port, host) {
  return new Promise(resolve => {
    const probe = net.createServer()
    probe.once('error', () => resolve(false))
    probe.once('listening', () => probe.close(() => resolve(true)))
    probe.listen({ host, port })
  })
}

async function nextAvailablePort(startPort, host) {
  for (let port = startPort; port <= 65535; port += 1) {
    if (await availablePort(port, host)) return port
  }
  throw new Error(`No available TCP port was found from ${startPort} through 65535.`)
}

if (process.argv.includes('--help') || process.argv.includes('-h')) {
  console.log('Usage: orbit run')
  process.exit(0)
}
if (process.argv[2] !== 'run') {
  console.log('Usage: orbit run')
  process.exit(1)
}

if (!existsSync(venvPython)) {
  console.log('Creating Python virtual environment…')
  run(python, [...pythonVersionArgs, '-m', 'venv', '.venv'])
}
console.log('Preparing Python runtime…')
run(venvPython, ['-m', 'pip', 'install', '.'])
if (!existsSync(join(root, 'frontend', 'dist', 'index.html'))) {
  console.error('The OpenOrbit package does not contain the built web app.')
  console.error('Install a published package, or run `pnpm run build` from a source checkout.')
  process.exit(1)
}

const host = process.env.ORBIT_HOST || '127.0.0.1'
const requestedPort = Number(process.env.ORBIT_PORT || '3000')
if (!Number.isInteger(requestedPort) || requestedPort < 1 || requestedPort > 65535) {
  throw new Error('ORBIT_PORT must be an integer from 1 through 65535.')
}
const port = await nextAvailablePort(requestedPort, host)
const localUrl = `http://127.0.0.1:${port}`
console.log(`OpenOrbit is starting. Open ${localUrl}`)
if (port !== requestedPort) {
  console.log(`Port ${requestedPort} is in use; using ${port} instead.`)
}
if (process.env.ORBIT_PUBLIC_URL) {
  console.log(`Public URL: ${process.env.ORBIT_PUBLIC_URL.replace('{port}', String(port))}`)
}
const server = spawn(venvPython, ['-m', 'uvicorn', 'app.main:app', '--app-dir', 'backend', '--host', host, '--port', port], { cwd: root, stdio: 'inherit' })
process.on('SIGINT', () => server.kill('SIGINT'))
process.on('SIGTERM', () => server.kill('SIGTERM'))
server.on('exit', code => process.exit(code ?? 0))
