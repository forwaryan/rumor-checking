# Repository Agent Guide

## Scope

These instructions apply to the entire repository. More specific `AGENTS.md` files may refine them for a subtree.

## Architecture

- `backend/app/api/`: FastAPI transport only; keep domain decisions out of endpoints.
- `backend/app/services/`: fact-checking pipeline, retrieval, verdict, reporting, and observability.
- `backend/app/agent/`: agent runtime, checkpoints, permissions, budgets, and multi-agent orchestration.
- `frontend/`: Next.js UI and streamed-analysis client.
- `contracts/`: public JSON contracts shared by backend and frontend.
- `evals/`: deterministic fixtures and live-replay snapshots.

## Change Rules

- Prefer extending the current runtime over adding another agent framework.
- Keep offline tests deterministic; mark genuinely live tests with `@pytest.mark.slow`.
- Never commit API keys, internal gateway addresses, cookies, captured private pages, or raw user data.
- Update JSON Schema, Pydantic models, and TypeScript interfaces together.
- Record durable architecture decisions in `docs/adr/`.
- Do not weaken evidence requirements merely to improve aggregate replay scores.

## Verification

Run the smallest relevant checks first, then the complete local gate:

```bash
python backend/scripts/check_contracts.py
python -m pytest backend/tests/ -q
ruff check backend/
cd frontend && npm run typecheck && npm test && npm run build
python backend/scripts/replay_eval.py --output artifacts/replay-local.json
```

Document any check that cannot run and why.
