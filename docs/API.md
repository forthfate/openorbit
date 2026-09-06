# OpenOrbit API v1

OpenOrbit exposes a local, versioned HTTP API at `/api/v1`. The resource names
are intentionally similar to GitLab: an evaluation build is a **project**, and
each execution is a **pipeline**. The interactive OpenAPI documentation is
available from a running server at `/api/docs`; the raw contract is
`/api/openapi.json`.

## Local-first security

The API has no built-in authentication in this release. It is intended for the
local control room and local automation. Do not publish the server directly to
the Internet. Put a reverse proxy with authentication, TLS, and an allowlist in
front of it before allowing remote clients.

## API conventions

- All paths below are relative to `/api/v1`; requests and responses use JSON.
- `GET /api/v1` advertises the API version and the documentation contract URLs.
- Identifiers are URL path segments. Encode a model profile name when it has a
  space or other reserved character.
- Successful creation returns `201`; successful deletion returns `204` with no
  body. Unknown resources return `404`; invalid state transitions or unsafe
  configuration return `409`; invalid request data returns `422`.
- API errors follow FastAPI's JSON shape, for example
  `{"detail":"대상을 찾을 수 없습니다."}`.
- Secrets are never sent to or stored by the API. A model profile contains only
  the environment-variable name such as `AZURE_OPENAI_API_KEY`.

## Resources

| Resource | Meaning | Main endpoints |
| --- | --- | --- |
| Project | An evaluation-build configuration, including its workflow and repository | `GET, POST /api/v1/projects` |
| Pipeline | One `run` or `test` execution of a project | `GET /api/v1/pipelines`, `POST /api/v1/projects/{id}/pipelines` |
| Workflow | Reusable lifecycle definition | `GET, POST /api/v1/workflows` |
| Runner | Local executable runner source | `GET, POST /api/v1/runners` |
| Asset | Runner template, prompt template, or test case set | corresponding plural resource path |
| Model profile | Provider settings, selected on upsert | `GET, PUT /api/v1/model-profiles/{name}` |

Collection endpoints accept `page` (starting at 1) and `per_page` (1–100).
They return GitLab-style pagination headers: `X-Total`, `X-Total-Pages`,
`X-Page`, `X-Per-Page`, `X-Next-Page`, and `X-Prev-Page`.

## Endpoint coverage

| Area | Endpoints |
| --- | --- |
| System | `GET /health`, `GET /system/docker` |
| Projects | `GET, POST /projects`; `GET, PUT, DELETE /projects/{id}` |
| Pipelines | `GET /pipelines`; `GET /pipelines/{id}`; `POST /projects/{id}/pipelines`; `POST /workflows/{id}/pipelines`; `POST /pipelines/{id}/actions`; `POST /pipelines/actions/emergency-stop` |
| Pipeline evidence | `GET /active-pipelines`; `GET /pipelines/{id}/telemetry` |
| Workflows | `GET, POST /workflows`; `GET, PUT, DELETE /workflows/{id}` |
| Runners | `GET, POST /runners`; `GET, PUT, DELETE /runners/{id}`; `POST /runners/{id}/actions/open-vscode` |
| Runner templates | `GET, POST /runner-templates`; `GET, PUT, DELETE /runner-templates/{id}` |
| Prompt templates | `GET, POST /prompt-templates`; `GET, PUT, DELETE /prompt-templates/{id}` |
| Test case sets | `GET, POST /test-case-sets`; `GET, PUT, DELETE /test-case-sets/{id}` |
| Model profiles | `GET /model-profiles`; `GET, PUT, DELETE /model-profiles/{name}`; `POST /model-profiles/test` |
| Local configuration | `GET, PUT /application-settings`; `GET /workspaces?path=…` |
| Observability | `GET /dashboard`, `/telemetry`, `/logs` |
| Improvements | `GET /improvements`, `/improvements/analytics?hours=24`, `/improvements/interventions`, `/improvements/proposal-decisions`, `/improvements/proposals?evaluation_build_id=…&status=…`, `/reported-issues` |

## Common workflow

```bash
# Inspect projects
curl http://localhost:3000/api/v1/projects

# Start a safe test execution for a project
curl -X POST http://localhost:3000/api/v1/projects/my-project/pipelines \
  -H 'Content-Type: application/json' \
  -d '{"execution_mode":"test"}'

# Read its latest state
curl http://localhost:3000/api/v1/pipelines/PIPELINE_ID

# An approval-gated run can be approved, rejected, or cancelled
curl -X POST http://localhost:3000/api/v1/pipelines/PIPELINE_ID/actions \
  -H 'Content-Type: application/json' \
  -d '{"action":"approve"}'
```

Creating or replacing a project uses the same configuration fields as the
control room's evaluation-build form. Refer to `/api/docs` for the generated
`EvaluationBuildCreate` schema and validation rules.

## Compatibility

The older `/api/*` routes remain the control-room's internal API. New scripts
and integrations should target `/api/v1` only. A future breaking change will
be introduced under a new versioned prefix rather than changing v1 semantics.
