# Improvement evidence loop

Status: accepted

## PDCA cycle

1. **Plan**: a configured supervisor can return structured findings and improvement proposals from retained runner evidence.
2. **Do**: native improvement runners may record a candidate fingerprint and rollback-protected file history.
3. **Check**: the supervisor records a score and approval/rejection outcome when a model profile is configured.
4. **Act**: operators review retained evidence; Orbit does not automatically apply a source change, commit or revert.

## Evidence and feedback

Runs retain prompt snapshots, runner results, supervisor responses, score/decision data and trace IDs. Availability of a candidate fingerprint, diff summary and rollback history depends on the runner.

## Commit and rollback

Git commits, patch reverts and PR creation are not implemented by Orbit.

## Planned work

Add isolated candidate diffs, baseline comparison, policy-driven approval, reviewed Git commit/revert and optional PR evidence attachment.
