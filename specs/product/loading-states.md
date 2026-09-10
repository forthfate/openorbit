# Control-room loading states

Status: accepted

## Goal

Make the first visit to every control-room view feel intentional while its
data is loading, without making routine background refreshes visually noisy.

## Initial loading contract

- A view must expose a skeleton that resembles its final section layout before
  its first required data request resolves.
- Skeletons are structural placeholders, not progress indicators. They must
  not present invented values, empty-state messages, or enabled record actions.
- List and table views use row-shaped placeholders. Metric, chart, and form
  views use placeholders that preserve their section's visual footprint.
- Assets use section-shaped placeholders rather than individual catalog rows,
  because several independently managed asset collections load together.
- The dashboard, assets, builds, runs, settings, and
  improvements views all provide an initial loading state.

## Independent section requests

Some sections fetch data independently of the control-room bootstrap request.
Those sections maintain their own `initialLoading` state and show a section
skeleton until their first request settles. This currently includes dashboard
operational health, feedback trends, and improvement analytics.

An error ends initial loading. The section then shows its normal empty or
error-safe state rather than an indefinite skeleton.

## Refresh behavior

Skeletons are first-load only:

- Periodic polling, explicit refreshes, filter changes, and mutations retain
  the currently visible content while new data is requested.
- A completed initial load must not switch back to a skeleton solely because a
  refresh starts.
- Loading controls for a deliberate user action may show their own disabled or
  pending state; they are separate from the page's initial skeleton contract.

## Accessibility and motion

- Skeleton containers expose a loading status to assistive technology while
  their section is unavailable.
- Decorative bars are hidden from assistive technology.
- Shimmer animation respects `prefers-reduced-motion`.

## Implementation boundary

Reusable skeleton primitives belong in `frontend/src/components/ui/`. Feature
pages choose the number and shape of section placeholders; they do not create
ad-hoc loading semantics. The global control-room data hook owns bootstrap
loading, while a feature owns the initial state of any API request it starts.
