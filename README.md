# AI Study Coach — a tutor that adjusts the plan as you learn

A personalised AI study tutor. What sets it apart from a chat window is that it
**watches how the learning is going and rewrites the plan**: set a goal, the AI
drafts a route, you study it, you answer questions, the AI grades them, and the
route changes in response.

**This is an early-stage repository.** Two milestones are built — the
application skeleton with authentication (M0) and the multi-provider LLM layer
(M1). The learning features themselves are not implemented yet: there is no
route generation, no lesson content, no grading, and the dashboard is a shell
that proves you are signed in. What exists is the load-bearing infrastructure
those features will sit on, and it is built and tested in earnest rather than
sketched.

Read [`docs/BAN-GIAO.md`](docs/BAN-GIAO.md) before changing anything. It records
the invariants that fail *silently* if broken — nine of them, each already paid
for once.

## Features

- **Accounts and sessions**
  - Register and sign in with email and password, hashed with argon2.
  - Access and refresh tokens (PyJWT HS256), with refresh rotation and
    revocation recorded in the database.
  - Next.js acts as a **BFF**: the JWT lives only in `httpOnly` cookies, so
    browser JavaScript can never read it. `BACKEND_URL` is server-only and
    deliberately carries no `NEXT_PUBLIC_` prefix.
  - Sessions expire after 15 minutes of inactivity — silent token refresh is
    not built yet, so you sign in again.

- **Multi-provider LLM layer, running on free tiers**
  - Gemini, Groq and Mistral behind one facade (`LLMService.run()`). A caller
    names a task, not a vendor.
  - **Routing with fallback**: when a provider is rate-limited, out of quota,
    unavailable, or returns output that does not match the schema, the call
    moves to the next provider instead of waiting. A `retry_after` hint is
    recorded, never slept on.
  - **Structured output with a degrade ladder**: coerce, validate, retry. Gemini
    is the only provider that enforces a JSON schema natively; Groq and Mistral
    declare no such capability, because `json_object` mode guarantees valid
    syntax and nothing about the shape.
  - **Rate limiting that holds across processes**: a token bucket in a single
    Redis Lua script, with time read from Redis rather than from any app
    process. When Redis is unreachable the call is refused rather than let
    through — the wrong refusal costs one retry, the wrong pass loses the only
    shared ceiling there is.
  - **Every call is accounted for**, including the ones that failed and the
    retries that were thrown away. Token usage is written to a ledger in its own
    transaction, so a failed bookkeeping write can never destroy an answer that
    has already been paid for.
  - **BYOK key vault**: user-supplied provider keys sealed with AES-GCM — a
    fresh random nonce per encryption, and a version byte in the blob so adding
    AAD later is a clean migration rather than a cut-off date.
  - **Fixture record and replay** for provider responses, so the suite runs
    offline without spending quota.

- **Privacy constraint of running on free tiers**
  - Free-tier prompt data may be used to train third-party models, so **no
    identifier ever enters a prompt** — no email, no name, no real `user_id`.
    Anonymous ids only. This is a live constraint on new code, not a historical
    note.

- **Secrets stay out of errors**
  - The 422 handler masks offending values, recursively and including
    body-level validation errors where the input is the whole request body.
  - Secret shapes are checked with ordinary code, never a pydantic validator —
    a `ValidationError` echoes the offending value into its own message.
  - Network failures are reported by `type(exc).__name__`, because an httpx
    exception repr can carry a URL and a URL can carry a key. API keys travel in
    headers, never in a query string.

### Not built yet

Goal setting, route generation, lesson content, the tutor chat, answer grading,
progress tracking and the rule-based route adjustment (R1–R4) are all designed
but unimplemented. A daily quota breaker is also missing: the bucket limits per
minute only, so `QuotaExhausted` and `RateLimited` currently behave alike. See
§5 and §6 of the handover document for the full list and the reasoning.

The schema-compliance measurement that M1 exists to enable **has not been run**
— it needs real API keys and a day's free quota. Until it does, the `ROUTING`
and `PROVIDER_RPM` tables in `routing.py` hold provisional values, marked as
such in the code.

## Tech Stack

- **Backend**: Python 3.12, FastAPI, async SQLAlchemy, Alembic, pydantic-settings
- **Data**: PostgreSQL 16, Redis 7
- **Auth**: argon2 password hashing, PyJWT (HS256)
- **LLM providers**: Gemini (native JSON schema), Groq and Mistral (OpenAI-compatible)
- **Crypto**: AES-GCM via `cryptography`
- **Frontend**: Next.js 16, React 19, TypeScript — used as a BFF, not a SPA
- **Testing**: pytest (301 tests, requires a real PostgreSQL), ruff for lint and format

## Running

Local infrastructure:

```bash
docker compose up -d      # PostgreSQL on host port 15432, Redis on 6379
```

**PostgreSQL is on 15432, not 5432** — the original development machine had a
native server holding 5432, 5433 and 55432, and the decision was to move the
Docker side rather than touch a system service. Keep 15432 even on a machine
with 5432 free, so nothing drifts from `.env.example` and `conftest.py`.

Backend, from `backend/`:

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"   # Windows
# .venv/bin/python -m pip install -e ".[dev]"         # Linux/macOS

cp ../.env.example .env    # then fill in JWT_SECRET and LLM_KEY_ENCRYPTION_KEY
.venv/Scripts/alembic.exe upgrade head
.venv/Scripts/python.exe -m uvicorn app.main:app --reload   # API on :8000
.venv/Scripts/python.exe -m pytest -q                       # 301 passed
.venv/Scripts/python.exe -m ruff check .
```

`LLM_KEY_ENCRYPTION_KEY` must decode from base64 to **exactly 32 bytes**. Generate one:

```bash
.venv/Scripts/python.exe -c "from app.modules.llm.keyvault import generate_master_key; print(generate_master_key())"
```

Leaving it unset is fine — BYOK is simply off. Setting it to the *wrong length*
fails at startup on purpose: `AESGCM` silently accepts 16- and 24-byte keys, so
without that check a misconfiguration would quietly weaken encryption forever.

Frontend, from `frontend/`:

```bash
npm install
cp .env.example .env.local   # BACKEND_URL=http://localhost:8000
npm run dev                  # :3000
npm run lint
npx tsc --noEmit
```

Two things worth knowing before running commands: run `ruff` from `backend/`
(the root `ruff.toml` exists only to keep `docs/` out of scope — `ruff format`
has rewritten Markdown code blocks and overwritten two planning documents), and
the tests need a real PostgreSQL whose database name ends in `_test`, which
`conftest.py` enforces by raising.

## Project structure

```
backend/
  app/
    main.py            FastAPI app, /health, 422 handler that masks secrets
    config.py          Settings (pydantic-settings)
    db.py              async engine, session factory, Base
    models.py          THE ONLY model registry — never delete an import here
    security.py        argon2 + JWT
    modules/auth/      router, service, deps, models, schemas
    modules/llm/
      types.py         CallSpec, Usage, Capability, the LLMError tree
      registry.py      prompt + Pydantic output model per task type
      providers/       gemini · openai_compat · groq · mistral
      routing.py       provider choice and fallback
      degrade.py       JSON degrade ladder: coerce -> validate -> retry
      ratelimit.py     token bucket, Redis Lua
      keyvault.py      AES-GCM BYOK vault
      ledger.py        token ledger
      service.py       LLMService — THE ONLY facade
  alembic/versions/    0001 users · 0002 refresh_tokens · 0003 token_ledger
  scripts/             measure_json_compliance.py
  tests/

frontend/
  app/api/auth/{register,login,logout,refresh}/route.ts   BFF route handlers
  app/{login,register,dashboard}/                          pages
  lib/session.ts     httpOnly cookies (sc_access, sc_refresh)
  lib/backend.ts     BACKEND_URL — server-only

docs/
  BAN-GIAO.md        handover: invariants, gaps, what to do next — read first
  design/            product and UI decisions
  superpowers/       specs and plans
```

---

**Documentation is in Vietnamese**; `docs/BAN-GIAO.md` is the entry point.
