# My Inner Pages — Backend

Python 3.11+ FastAPI server with MongoDB/Beanie, LangChain AI, JWT auth.

## Commands (run from `backend/`)
- `uv sync` — install dependencies
- `uv run fastapi dev app/main.py` — dev server with hot reload
- `uv run pytest` — run all tests (async, isolated test DB)
- `uv run pytest tests/E2E/auth/ -v` — run specific test module
- `uv add <package>` — add dependency

## Non-obvious tooling
- `uv` instead of pip — Rust-based package manager, uses `uv.lock`
- `hatchling` as build backend
- `structlog` for structured logging (key-value pairs)

## Architecture
- **Domain modules:** `auth/`, `journals/`, `chat/`, `ai/`, `memory/`
- **Shared infra:** `core/` (config, logging, middleware, rate-limit, cache, deps)
- **Layer pattern per module:** `api/routes/` → `facade/` or `service/` → `db/repository.py`
- **DI:** Routes use `Depends(get_*)` — never instantiate services directly
- **Route prefix:** `/api/v0` set in `main.py`

## Error monitoring (Sentry)
- DSN configured via `SENTRY_DSN` env var (optional — if empty, Sentry is a no-op)
- Initialized in `app/main.py` via `app/core/error_monitoring.py`
- `init_sentry()` with FastAPI/Starlette integrations, configurable `traces_sample_rate` and `profiles_sample_rate`
- Tags every event with `container_id` (for blue/green debugging) and `hostname`
- Global 5xx exception handler in `main.py` captures request context (method, URL, client IP, query string) to Sentry
- MongoDB connection retry exhaustion sends a Sentry event before raising
- Slow requests (>5s) are reported as Sentry warnings from `RequestLoggingMiddleware`
- `capture_exception()` utility in `error_monitoring.py` for manual reporting of handled-but-worthy errors
- Development: Sentry is disabled locally unless `SENTRY_DSN` is set; use `sentry-sdk`'s no-op behavior

## Email verification
- Implemented via Resend SDK (`resend` PyPI package)
- `EmailService` in `app/core/services/email_service.py` wraps `resend.Emails.send()`
- Verification tokens are 32-byte URL-safe random strings, stored on the `User` document
- Token expiry configurable via `AuthModuleConfig.verification_token_expire_hours` (default: 24h)
- Set `EMAIL_VERIFICATION_REQUIRED=false` in `.env` to skip verification in dev/test (auto-verifies on register)
- `FROM_EMAIL` defaults to `support@innerpages.ir` — change via `.env`
- `VERIFICATION_URL_BASE` controls the link in the email (default: `http://localhost:5173?verify=`)

## Key conventions
- **Type hints:** mandatory on all function signatures
- **Docstrings:** Google-style with Args/Returns/Raises
- **Logging:** `structlog.get_logger(__name__)`, key-value pairs
- **Responses:** Pydantic schemas with `from_document()` classmethod
- **Errors:** facades raise `ValueError`; routes catch → `HTTPException`
- **Imports:** stdlib → third-party → local (absolute from `app.`)
- **Email service:** `EmailService` is injected via DI (like `JWTService`) — configured in `core/deps/services.py`, used through `AuthFacade`
- **Testing:** async tests (`@pytest.mark.asyncio`), fresh test DB per test, mock LLM enforced
- **Routes are glue:** authenticate, validate, call a facade/service, translate errors — no business logic, no orchestration
- **Facade vs Service:** a *facade* owns business logic (orchestration + domain rules); a *service* holds reusable functionality that is not specific to a single business flow (helpers, cross-cutting concerns). If it orchestrates multiple steps or enforces domain rules, it belongs in a facade.

## AI-specific notes
- `USE_MOCK_LLM=true` in `.env` for offline dev — avoids API costs
- Test suite auto-enables mock LLM via conftest fixture overrides
- LLM client selected via `get_llm_client()` dependency in `ai/deps.py`. It queries active model configs from MongoDB asynchronously and caches the client singleton via `@lru_cache` based on the serialized configuration hashes.
- If no providers are configured in the database, the client automatically falls back to `MockLLMClient` to prevent system crashes.
- Configurations are stored in MongoDB via the `LLMProvider` Beanie Document and retrieved using the `LLMProviderRepository` in `ai/db/repository.py`.
- API keys in the database configuration support environment variable placeholders using the shell-style format `"${ENV_VAR_NAME}"` (e.g. `"api_key": "${OPENROUTER_API_KEY}"`), which are dynamically resolved at runtime. Obfuscation logic in routes prevents exposure of actual keys.

## Boundaries
- Do NOT commit `.env` files or real API keys
- Do NOT use synchronous PyMongo — use async Motor
- Do NOT bypass `get_current_user()` — always validate auth
- Do NOT hardcode secrets — use `Settings` from pydantic-settings

## SSE chat streaming

The AI chat uses SSE streaming over `POST /api/v0/chat/stream` instead of WebSockets. This eliminates the need for ConnectionManager, GenerationManager, and MessageDedupStore — the connection lifecycle is managed entirely by FastAPI's `StreamingResponse` and HTTP semantics. Authentication is via HttpOnly `access_token` cookie (same as all other endpoints). Rate limiting uses the programmatic `check_rate_limit()` function. Client cancellation is handled via `asyncio.CancelledError` when the HTTP connection drops.

## Reference docs
- `README.md` — setup guide, API endpoint reference, SSE chat protocol, .env config
- `docs/architecture/` — architecture deep-dives, DI wiring, database design
- `docs/features/` — feature-specific docs (authentication, tag system, caching, rate limiting, chat, user model, LLM providers)
