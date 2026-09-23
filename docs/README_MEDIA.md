# README product-tour media

The product-tour media in the README must show the current English interface
and be reproducible from sanitized local data. Capture neither a personal
workspace nor real API credentials, private paths, or conversations.

The README tells one continuous story: start with a Quick Start, inspect what
the target AI did, review the improvement history, review AI-created work, and
ask the local Assistant for help. Keep those five captures coherent by using
the same prepared demo AppData for all of them.

## Shared capture contract

Before capturing any asset:

1. Use the maintained, sanitized README demo AppData. It must contain the
   representative customer-support Build, its retained Runs and evidence, an
   approved improvement, and enough history for the Improvements charts. Never
   rely on a personal default AppData directory.
2. Start the locally built application on port 3080. Replace the placeholder
   with the explicit path to the prepared demo AppData:

   ```bash
   ORBIT_APP_DATA=/path/to/sanitized-readme-demo-app-data \
     uv run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 3080
   ```

3. Use Selenium with a headless Chrome browser. Set the interface language to
   English by setting `orbit.locale` to `en` in local storage, then reload.
4. Use the default dark theme and device scale factor 1. Capture PNGs at
   exactly 1024 × 768 and the Quick Start GIF at exactly 1024 × 640. Save the
   viewport directly: do not crop or resize it afterwards.
5. Before committing, confirm that visible labels use the current product
   vocabulary (`Builds`, `Runs`, `Improvements`, and `Run detail`) and that no
   stale release label, secret, personal path, or private data is visible.

## Quick Start GIF

`docs/images/openorbit-quick-start.gif` introduces the fast path for a new
operator. It should show the Dashboard, the Quick starts section, the guided
setup for **Continuous user journey**, the created Build, and a Test opening
its Run detail.

1. Open `http://127.0.0.1:3080/dashboard` with the prepared demo AppData.
2. Clear stored Assistant position values and ensure the Assistant is closed
   so the Quick starts cards remain unobstructed.
3. Start recording at the Dashboard with the Quick starts cards in view.
4. Open **Continuous user journey**, enter the prepared demo URL, persona, and
   goal, then review and create the Build. Do not enter a provider key.
5. In **Builds**, show the created Build, start **Test**, and end with its Run
   detail visible.
6. Save the recording as `docs/images/openorbit-quick-start.gif` at
   1024 × 640. Check that the motion is brief, readable, and does not loop
   through unrelated UI.

## Run detail image

`docs/images/evaluation-result-approved.png` shows a retained Run's workflow,
lifecycle progress, and the evidence available for review.

1. Open the retained customer-support Run from **Runs**.
2. Open **Run detail** and select the view that shows its completed workflow
   graph and Result tab.
3. Keep the Run status, lifecycle progress, workflow graph, and evidence
   summary readable in the 1024 × 768 viewport.
4. Save the viewport directly to
   `docs/images/evaluation-result-approved.png`.

## Improvements image

`docs/images/improvement-cycle-healthy.png` shows the value of retained history
across a Build rather than the result of one isolated Run.

1. Open `http://127.0.0.1:3080/improvements`.
2. Select a prepared Build with retained persona evidence and scroll to its
   **Persona journey timeline**.
3. Keep the selected Build's Run history and persona actions, decisions, and
   next steps readable in the 1024 × 768 viewport. Do not show empty states,
   stale filters, or unrelated Builds.
4. Save the viewport directly to
   `docs/images/improvement-cycle-healthy.png`.

## AI-created proposal image

`docs/images/ai-created-proposal-review.png` shows the approval boundary around
an AI-created change rather than implying that a proposal is applied
automatically.

1. Open `http://127.0.0.1:3080/improvements` and select the prepared
   self-improvement Build with a retained agent proposal.
2. Scroll to **Issue management**, open the AI-created proposal, and keep its
   rationale, generated diff, isolated proposal branch, and approval actions
   visible together.
3. Use the English UI and prepared English proposal data. Do not show private
   worktree paths, provider credentials, or private repository content.
4. Save the 1024 × 768 viewport directly to
   `docs/images/ai-created-proposal-review.png`.

## Orbit Assistant improvements image

`docs/images/chat-assistant-question.png` shows **Improvements** with the Orbit
Assistant open. Enter the following draft message, but do not send it:

> Please analyze the improvements shown on this screen and suggest the safest
> next action.

1. Open `http://127.0.0.1:3080/improvements` and select the prepared Build
   that has a retained **Persona journey timeline**.
2. Scroll until the Build's recent Run and persona actions are visible, then
   clear the stored Assistant position values, reload, and open **Orbit
   assistant**. This keeps the default Assistant placement reproducible.
3. Enter the draft message above without sending it, while keeping the visible
   improvement evidence readable behind the Assistant.
4. Save the 1024 × 768 viewport directly to
   `docs/images/chat-assistant-question.png`. Confirm that the Improvements
   view, the open Assistant, its available-tools summary, and the draft
   message are readable.

## Final review

View every generated asset at its final size before committing. The five assets
should read as one product story and show the same current English UI state. If
the interface changes in a way that makes a capture stale, update both the
asset and this guide in the same change.
