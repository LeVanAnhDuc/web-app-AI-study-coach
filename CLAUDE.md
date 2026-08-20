# AI Study Coach (app-AI-study-coach)

A personalised AI study tutor: it generates a learning path, teaches it, grades answers and adjusts the plan. Python 3.12 / FastAPI backend (async SQLAlchemy on Postgres 16, Redis 7, Alembic, argon2 + JWT auth) with a Next.js 16 / React 19 / TypeScript frontend acting as a BFF; LLM content comes from the Gemini, Groq and Mistral free tiers behind an in-house routing layer.

## Commands

Run backend commands from `backend/` (virtualenv at `backend/.venv`), frontend commands from `frontend/`.

```bash
docker compose up -d           # local infra: Postgres on host port 15432, Redis on 6379

pip install -e ".[dev]"        # backend deps (backend/)
alembic upgrade head           # apply migrations
uvicorn app.main:app --reload  # dev API on :8000
pytest -q                      # 301 tests; needs a real Postgres, DB name must end in _test
ruff check .                   # lint — real config is backend/pyproject.toml
ruff format .                  # format

npm install                    # frontend/
npm run dev                    # Next.js dev server on :3000
npm run build
npm run lint                   # eslint
npx tsc --noEmit               # typecheck (there is no backend type checker configured)
```

## README (REQUIRED — keep in sync with features)

`README.md` describes what the app does for its users — it is not a boilerplate page. Every commit that adds or changes user-facing behaviour (`feat:`) MUST update the `## Features` section of `README.md` in the same branch, before merging — one short English bullet in the existing style.

While touching README, refresh any stale numbers you notice (test counts, stack versions).

README-only documentation commits use a `docs:` prefix.
