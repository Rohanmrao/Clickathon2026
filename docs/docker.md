# Running the whole stack with Docker

One command brings up the stack as separate containers. **The RCA ClickHouse stays external**
(Cloud, via `.env`) — so does **Langfuse, by default**: this backend talks to the team's ONE
shared self-hosted instance at `https://traces.kangasys.com`, not a fresh instance per machine.
That's deliberate — Langfuse packaged in `docker-compose.yml` used to mean every
`docker compose up` minted an *independent* instance with its own trace database, so a trace
recorded on one machine 404'd when read from another (same YAML, unrelated servers, nothing
synced). See the comment block at the top of `docker-compose.yml` for the full story.

| Service        | Container(s)                                   | URL                    | Notes |
|----------------|------------------------------------------------|------------------------|-------|
| Dashboard      | `frontend` (nginx)                             | http://localhost:5173  | The React UI |
| Backend        | `backend` (FastAPI)                            | http://localhost:8000  | `/health`, `/investigate`, `/v1/chat/completions` |
| Langfuse       | — (external, shared)                           | https://traces.kangasys.com | Self-hosted **v3**, but only ONE instance for the whole team |
| LibreChat      | `api` + `mongodb`                              | http://localhost:3080  | Conversational RCA UI |
| RCA ClickHouse | — (external Cloud)                             | your `CLICKHOUSE_HOST` | Not a container |

## Run it

```bash
cp .env.example .env
# Fill CLICKHOUSE_*. Get your own Langfuse key from https://traces.kangasys.com (log in — don't
# sign up — then Project Settings -> API Keys -> Create) and fill LANGFUSE_PUBLIC_KEY/SECRET_KEY.
# (Optional) add AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY to enable Bedrock narration.

docker compose up --build
```

Only two local images to build (backend, frontend) — no Langfuse infra to pull or migrate, since
it isn't running here. Compose auto-merges `docker-compose.override.yml`, which mounts
`librechat.yaml`.

Then open **http://localhost:5173**.

Stop with `Ctrl-C`; `docker compose down` to remove containers (add `-v` to wipe the Mongo
volume).

### Prefer a fully local, offline Langfuse instead?

```bash
COMPOSE_PROFILES=self-hosted-langfuse docker compose up --build
```

This starts the full `langfuse-web` / `-worker` / `-postgres` / `-clickhouse` / `-redis` /
`-minio` stack that used to run by default. Uncomment the matching block in `.env.example` (sets
`LANGFUSE_HOST` and `LANGFUSE_PUBLIC_HOST` to `http://localhost:3000` — leaving only one set
would ingest into your local instance while trace links still opened the shared one's UI). Your
traces stay on your machine and are invisible to teammates and to `traces.kangasys.com`.

> **Backend needs the v4 Langfuse SDK.** The tracing code uses `propagate_attributes` /
> `start_as_current_observation` (Langfuse SDK v3/v4). `backend/Dockerfile` installs `langfuse>=3`
> for this reason — an older SDK ImportErrors and 500s `/investigate`.

## How the wiring works

- **Backend → ClickHouse**: `CLICKHOUSE_*` from `.env`. If unset/unreachable the backend still
  boots and serves **fixture mode** (`/health` reports `engine: fixture`).
- **Backend → Langfuse**: `LANGFUSE_HOST` defaults to `https://traces.kangasys.com`, the team's
  shared instance — set `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` to your own personal key
  from there. Only under `COMPOSE_PROFILES=self-hosted-langfuse` does it point at the internal
  `langfuse-web:3000`, seeded via `LANGFUSE_INIT_*` with whatever keys you put in `.env`.
- **Frontend → Backend / LibreChat**: Vite bakes `http://localhost:8000` and
  `http://localhost:3080` at build time (host-browser URLs, since the browser runs on your
  machine). To change them, rebuild: `docker compose build frontend`.
- **LibreChat → Backend**: `librechat.yaml` points at `http://host.docker.internal:8000/v1`,
  i.e. the backend's published host port. `extra_hosts` makes that name resolve in the container.

## Narration (AWS Bedrock) in containers

The narrator authenticates via the AWS credential chain. A host venv reads `~/.aws`
automatically; the **container cannot see it**. To enable prose in Docker, put
`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` (and `AWS_SESSION_TOKEN` if using SSO) in `.env`.
Without them, investigations still run end-to-end — only the narrative is skipped.

## Trace links

By default `LANGFUSE_HOST` is already the browser-reachable `https://traces.kangasys.com`, so a
bundle's trace URL opens directly — log in there with your own account (**don't sign up**, that
creates a separate empty org invisible to the seeded project).

Only under `COMPOSE_PROFILES=self-hosted-langfuse` does `LANGFUSE_HOST` become the
container-internal `langfuse-web:3000`, which won't open from your browser; find those traces at
**http://localhost:3000** instead (log in as `admin@clickathon.local` / `LANGFUSE_INIT_USER_PASSWORD`).

## Gotchas

- **`.env` is required** — compose reads Langfuse keys from it. `cp .env.example .env` first.
- **Ports 3000 / 3080 / 5173 / 8000 must be free.** Change the left side of a `ports:` mapping
  in `docker-compose.yml` if one is taken.
- **LibreChat first visit**: registration is open (`ALLOW_REGISTRATION=true`) — create a local
  account, then pick **RCA Analyst** in the model dropdown.
- The `CREDS_KEY` / dev secrets in the compose file are for a throwaway local stack. Regenerate
  before exposing any of this beyond localhost.
