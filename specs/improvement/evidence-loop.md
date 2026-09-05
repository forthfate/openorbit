# Improvement evidence loop

Status: accepted

## PDCA cycle

1. **Plan**: AI proposes a bounded hypothesis, expected metric change, permitted paths and acceptance evidence.
2. **Do**: runner creates one isolated candidate diff and records its fingerprint.
3. **Check**: evaluator compares baseline and candidate evidence using configured criteria and score threshold.
4. **Act**: prompt-defined policy returns continue, approve-for-commit or revert; hard safety rules validate that response.

## Evidence and feedback

Every proposal retains prompt/policy version, source fingerprint, diff summary, baseline, evaluation result, effect metrics, decision rationale, trace IDs and a compact feedback record sent into the next AI evaluation.

## Commit and rollback

- Only an approved candidate with required evidence may be committed.
- The commit message/body records hypothesis, effect, score gate, trace/run IDs and rollback condition.
- An insufficient candidate is reverted from its recorded patch only; unrelated user changes block automation.
- PR creation is optional but, when enabled, the PR URL and status are attached to the same evidence record.
