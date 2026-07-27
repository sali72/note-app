from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthModuleConfig(BaseSettings):
    """Auth module specific configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    # JWT settings
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15  # 15 minutes (short-lived access token)
    refresh_token_expire_days: int = 30    # 30 days (long-lived refresh token)
    
    # Password settings
    min_password_length: int = 8
    max_password_length: int = 72
    
    # Email settings
    max_email_length: int = 255

    # Email verification
    email_verification_required: bool = True
    verification_token_expire_hours: int = 24
