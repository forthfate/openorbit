# Settings section patterns

Use these rules for settings and connection-management UI.

## Information hierarchy

- Treat an independently managed resource (for example, MCP connections) as a dedicated section, not as an input inside an unrelated settings section.
- Order sections from general application preferences, to global connections, to storage and operational configuration.
- Every section uses `PanelHeader` and `SectionInfo`, with the same description shown below the header using `section-description`.

## Summary before editing

- The default view shows a concise, truthful summary: configured status, item count, and useful identifiers.
- Use the shared summary-value typography for read-only configuration values; do not style them as headings, metrics, or prompt/source previews.
- Do not render large structured configuration (JSON, YAML, source) inline by default.
- Open structured editors from an explicit `Edit` action in a modal or dedicated editing state.
- Do not claim a connection is active unless runtime health is available; use “configured” or “registered” for saved configuration alone.

## Controls and copy

- Reuse shared action labels: use the common `Save` label for persistence, not resource-specific variants such as “Save MCP configuration”.
- Buttons containing an icon and label must keep the label on one line and use the existing `setting-actions`/button styling.
- Keep section typography, row borders, spacing, and action alignment consistent with the other settings sections.
- Add all visible copy and accessibility labels to every supported locale.
