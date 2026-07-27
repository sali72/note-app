# Backend Architecture with Dependency Injection

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      FastAPI Application                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    API Routes Layer                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Auth       │  │  Journals    │  │   Mirror     │      │
│  │   Routes     │  │   Routes     │  │   Routes     │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
                              │
                    Depends() injection
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Facades Layer                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ AuthFacade   │  │JournalFacade │  │MirrorService │      │
│  │              │  │              │  │              │      │
│  │ Business     │  │ Business     │  │ Business     │      │
│  │ Logic        │  │ Logic        │  │ Logic        │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
                              │
                    Depends() injection
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              Repositories & Services Layer                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   User       │  │  Journal     │  │  LLM         │      │
│  │ Repository   │  │ Repository   │  │ Service      │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   JWT        │  │  Password    │  │  Memory      │      │
│  │  Service     │  │  Service     │  │  Service     │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Data Layer                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   MongoDB    │  │  OpenRouter  │  │   Config     │      │
│  │   (Beanie)   │  │     API      │  │  Settings    │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
```

## Dependency Flow Example: Creating a Journal

```
1. HTTP POST /api/v0/journals
   │
   ▼
2. Route: create_journal()
   │ Depends(get_current_user)      → Authenticates user
   │ Depends(get_journal_facade)    → Injects facade
   ▼
3. JournalFacade.create_journal()
   │ Uses: self.repository          → Injected repository
   │ Uses: self.config               → Injected config
   ▼
4. JournalRepository.create()
   │ Uses: Beanie ODM
   ▼
5. MongoDB
   │
   ▼
6. Return Journal document
   │
   ▼
7. Convert to JournalResponse
   │
   ▼
8. Return JSON to client
```

## Dependency Injection Flow

```
Application Startup
        │
        ▼
┌───────────────────┐
│  get_settings()   │  ← @lru_cache (singleton)
│  Returns: Settings│
└───────────────────┘
        │
        ├─────────────────────────────────┐
        │                                 │
        ▼                                 ▼
┌───────────────────┐          ┌───────────────────┐
│ get_jwt_service() │          │ get_llm_service() │
│ Needs: Settings   │          │ Needs: Settings   │
└───────────────────┘          └───────────────────┘
        │                                 │
        ▼                                 ▼
┌───────────────────┐          ┌───────────────────┐
│get_auth_facade()  │          │get_mirror_service()│
│ Needs:            │          │ Needs:            │
│ - Repository      │          │ - LLM Service     │
│ - JWT Service     │          │ - Memory Service  │
│ - Password Service│          │ - Config          │
│ - Config          │          └───────────────────┘
└───────────────────┘
        │
        ▼
┌───────────────────┐
│ Route Handler     │
│ Uses: AuthFacade  │
└───────────────────┘
```

## Module Structure

### Auth Module
```
app/auth/
├── exceptions.py               # Custom domain exceptions (AuthException hierarchy)
├── api/routes/auth.py          # Routes (uses Depends)
├── facade/auth_facade.py       # Orchestration façade (delegates to sub-services)
├── db/
│   ├── models.py               # User & RefreshToken Beanie documents
│   ├── repository.py           # UserRepository — user account persistence
│   └── session_repository.py  # SessionRepository — refresh token lifecycle
├── services/
│   ├── cookie_service.py       # HttpOnly cookie get/set/clear
│   ├── token_blacklist.py      # Redis (+ in-memory fallback) family blacklist
│   ├── token_service.py        # JWT generation & SHA-256 token hashing
│   ├── session_service.py      # Full session lifecycle (RTR, revocation, listing)
│   └── user_agent_service.py  # User-Agent string → device/browser/OS parsing
├── config.py                   # Module config (token TTLs, email verification flag)
└── deps.py                     # Dependency providers ⭐
```

### Journals Module
```
app/journals/
├── api/routes/journals.py      # Routes (uses Depends)
├── facade/journal_facade.py    # Business logic
├── db/
│   ├── models.py               # Journal model
│   └── repository.py           # Data access
├── config.py                   # Module config
└── deps.py                     # Dependency providers ⭐
```

### AI Module
```
app/ai/
├── api/routes/
│   ├── chat.py                 # SSE streaming route — authenticates, rate-limits, delegates to ChatFacade
│   └── mirror.py               # REST route — delegates to MirrorService
├── facade/
│   └── chat_facade.py          # SSE chat streaming orchestrator (business logic)
├── services/
│   ├── chat_service.py         # LLM prompt building + streaming (reusable, not chat-SPA-specific)
│   └── mirror_service.py       # Mirror reflection logic
├── config.py                   # Module config
└── deps.py                     # Dependency providers ⭐
```

### Core Module
```
app/core/
├── deps/
│   ├── settings.py             # Settings singleton ⭐
│   ├── services.py             # Core services ⭐
│   └── database.py             # DB dependencies
├── services/
│   ├── jwt_service.py          # JWT handling
│   └── password_service.py     # Password hashing
├── config.py                   # App settings
├── db.py                       # Database manager
└── logging.py                  # Logging config
```

## Request Lifecycle

### 1. Authenticated Request
```
Client Request
    │
    ├─ Header: Authorization: Bearer <token>
    │
    ▼
FastAPI Route
    │
    ├─ Depends(get_current_user)
    │   │
    │   ├─ Depends(get_auth_facade)
    │   │   │
    │   │   ├─ Depends(get_jwt_service)
    │   │   │   │
    │   │   │   └─ Depends(get_settings) ← Cached
    │   │   │
    │   │   ├─ Depends(get_user_repository)    ← User account ops
    │   │   │
    │   │   └─ Depends(get_token_blacklist)    ← Redis blacklist
    │   │
    │   ├─ Verify token
    │   ├─ Load user from DB
    │   └─ Return User object
    │
    └─ Execute route handler with User
```

### 2. Creating a Journal Entry
```
POST /api/v0/journals
    │
    ├─ Body: {title, content, tags}
    │
    ▼
create_journal(request, current_user, facade)
    │
    ├─ current_user: User (from Depends)
    ├─ facade: JournalFacade (from Depends)
    │   │
    │   ├─ repository: JournalRepository
    │   └─ config: JournalModuleConfig
    │
    ├─ facade.create_journal(...)
    │   │
    │   ├─ Validate title
    │   ├─ Validate content
    │   ├─ Normalize tags
    │   │
    │   └─ repository.create(...)
    │       │
    │       └─ MongoDB insert
    │
    └─ Return JournalResponse
```

## Testing Architecture

### Unit Test (Facade)
```
Test Function
    │
    ├─ Create Mock Repository
    ├─ Create Real Config
    │
    ├─ Instantiate Facade(mock_repo, config)
    │
    ├─ Call facade.method()
    │
    └─ Assert behavior
```

### Integration Test (Route)
```
Test Function
    │
    ├─ Create Mock Facade
    │
    ├─ app.dependency_overrides[get_facade] = lambda: mock
    │
    ├─ TestClient(app).post(...)
    │
    ├─ Assert response
    │
    └─ app.dependency_overrides.clear()
```

## Key Design Principles

1. **Single Responsibility**: Each layer has one job
   - Routes: HTTP handling (glue — auth, validate, delegate, translate errors)
   - Facades: Business logic (orchestration + domain rules)
   - Repositories: Data access
   - Services: Reusable utilities not specific to a single business flow (cross-cutting helpers, integrations)

   > *Facade vs Service*: A facade owns business logic (it orchestrates multiple steps and
   > enforces domain rules). A service holds reusable functionality that is not tied to
   > one specific business flow, such as JWT signing, password hashing, or LLM client
   > wrappers. If you're debating where something goes: does it orchestrate? does it
   > enforce a domain rule? → facade. Otherwise → service.

2. **Dependency Inversion**: High-level modules don't depend on low-level
   - Routes depend on abstractions (facades)
   - Facades depend on abstractions (repositories)
   - Dependencies injected, not created

3. **Open/Closed**: Open for extension, closed for modification
   - Easy to add new dependencies
   - Easy to swap implementations
   - No need to modify existing code

4. **Interface Segregation**: Clients depend only on what they use
   - Routes only see facade interface
   - Facades only see repository interface
   - No unnecessary dependencies

5. **Liskov Substitution**: Can swap implementations
   - Mock repositories in tests
   - Different configs per environment
   - Alternative service implementations

## Performance Characteristics

### Settings Loading
- **Before**: O(n) - loaded on every request
- **After**: O(1) - loaded once, cached forever

### Service Creation
- **Before**: New instance per request
- **After**: Reused within request (FastAPI cache)

### Memory Usage
- **Before**: Multiple Settings instances
- **After**: Single Settings instance

### Testability
- **Before**: Hard to mock, tightly coupled
- **After**: Easy to mock, loosely coupled

## Security Considerations

1. **Token Verification**: Centralized in `get_current_user`
2. **User Authorization**: Checked at route level
3. **Input Validation**: Pydantic schemas + facade validation
4. **Error Handling**: Consistent HTTP exceptions
5. **Secrets Management**: Settings from environment variables

## Scalability

The current architecture supports:
- ✅ Horizontal scaling (stateless)
- ✅ Multiple workers (no shared state)
- ✅ Async operations (non-blocking)
- ✅ Database connection pooling
- ✅ Request-scoped resources

Future enhancements:
- Add caching layer (Redis)
- Add message queue (RabbitMQ/Celery)
- Add rate limiting
- Add circuit breakers
