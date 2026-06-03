# Langfuse (self-hosted) for DeerFlow

DeerFlow sends traces via env vars in the project root `.env`. This stack adjusts default host ports to avoid local conflicts:

| Service | Host port | Notes |
|---------|-----------|--------|
| Langfuse UI | **3100** | DeerFlow frontend uses 3000 |
| Redis | **6399** | Maps to container `6379`; avoids local Redis on 6379 |

## Quick start

```bash
# From repo root
make langfuse-up
```

Open http://localhost:3100, create an account, then create a project and copy **Public key** / **Secret key** into the repo root `.env`:

```bash
LANGFUSE_TRACING=true
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=http://localhost:3100
```

Restart Gateway (or your VS Code debug session) and run an agent chat; traces appear under the project in Langfuse.

## Commands

| Command | Action |
|---------|--------|
| `make langfuse-up` | Start Langfuse (Docker) |
| `make langfuse-down` | Stop Langfuse containers |
| `./scripts/langfuse.sh status` | Container health |
| `./scripts/langfuse.sh logs` | Follow `langfuse-web` logs |

## Cloud instead of self-hosted

Skip Docker and set in root `.env`:

```bash
LANGFUSE_TRACING=true
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

## Notes

- First startup can take 1–2 minutes (ClickHouse migrations).
- Python dependency `langfuse` is already in `backend/packages/harness`; run `cd backend && uv sync` if imports fail.
- LangSmith and Langfuse can both be enabled; see [README.md](../../README.md#langfuse-tracing).
