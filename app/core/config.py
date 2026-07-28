from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True
    )
    
    # MongoDB Configuration
    mongo_url: str = "mongodb://localhost:27017"
    database_name: str = "journaling_app"
    
    # Application Configuration
    environment: str = "development"
    app_name: str = "My Inner Pages"
    app_version: str = "0.1.0"  # auto-set from git tag in deploy; override via APP_VERSION env var
    bcrypt_rounds: int = 12
    
    # Rate Limiting Configuration
    rate_limit_enabled: bool = True
    rate_limit_default: str = "60/minute"

    # Redis Configuration
    redis_url: str | None = None

    # CORS Configuration
    cors_allowed_origins: tuple[str, ...] = ("http://localhost:5173",)
    cors_allow_credentials: bool = True

    # JWT Configuration
    jwt_secret_key: str  # No default — must be set via JWT_SECRET_KEY env
    
    # Resend Configuration
    resend_api_key: str | None = None

    # Email Configuration
    from_email: str = "support@innerpages.ir"
    verification_url_base: str = "http://localhost:5173?verify="

    # Sentry Configuration
    sentry_dsn: str | None = None

    # Google OAuth Configuration
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:5173/api/v0/auth/google/callback"

    # Frontend URL (for OAuth redirect)
    frontend_url: str = "http://localhost:5173"

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"
