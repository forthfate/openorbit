# README product-tour media

Product-tour screenshots in the README should show the current interface and be
reproducible from sanitized local data. Do not capture a personal workspace,
real API credentials, or private conversations.

## Orbit Assistant dashboard image

`docs/images/chat-assistant-question.png` is a 1024 × 768 PNG showing the
Dashboard with the Orbit Assistant open. Capture it with the interface set to
English and the following draft message entered, but not sent:

> I'd like to hear your thoughts on the user improvement cycle we're currently
> working on.

### Preparation

1. Use the maintained, sanitized test AppData that contains representative
   evaluation data. Set it explicitly; never rely on a personal default data
   directory.
2. Start the locally built application on port 3080:

   ```bash
   ORBIT_APP_DATA=/path/to/sanitized-test-app-data \
     uv run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 3080
   ```

3. Use Selenium with a headless Chrome browser. Set its emulated viewport to
   exactly 1024 × 768 at device scale factor 1, then save the viewport directly
   to `docs/images/chat-assistant-question.png`. Do not resize or crop it after
   capture.

### Capture steps

1. Open `http://127.0.0.1:3080/#dashboard`.
2. Set `orbit.locale` in local storage to `en`, clear the stored Assistant
   position values, and reload. This keeps the default Assistant placement
   reproducible.
3. Open **Orbit assistant** and enter the draft message above without sending
   it.
4. Save a 1024 × 768 PNG and visually confirm that the Dashboard, the open
   Assistant, its available-tools summary, and the draft message are readable.

Before committing, verify the image dimensions and inspect the final image for
credentials, private paths, personal data, or stale UI.
