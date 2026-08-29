# Contributing

## Development flow

1. Create a focused branch from `main`.
2. Keep changes small and avoid unrelated refactors.
3. Add or update regression tests before changing established behavior.
4. Update contracts and documentation in the same pull request.
5. Complete the pull-request checklist and include the commands you ran.

## Local checks

Backend:

```bash
pip install -r backend/requirements-dev.txt ruff
ruff check backend/
python backend/scripts/check_contracts.py
python -m pytest backend/tests/ -q
python backend/scripts/replay_eval.py --output artifacts/replay-local.json
```

Frontend:

```bash
cd frontend
npm ci
npm run typecheck
npm test
npm run build
```

## Evaluation changes

- Treat `evals/live_replay/seed/` as a regression corpus, not training data.
- Use `evals/live_replay/hard/` for difficult end-to-end replay cases and add focused assertions under `backend/eval_regression_tests/` when replay behavior must stay locked.
- Add cases for new failure modes rather than rewriting expected labels to fit current output.
- Report category-level changes for time-sensitive, stale-news, subject-mismatch, and conflicting-source cases.
- Keep retrieval snapshots free of secrets and personal data.

## Architecture decisions

Add an ADR from `docs/adr/0000-template.md` when a change introduces a framework, protocol, persistent service, public contract, or difficult-to-reverse dependency.
