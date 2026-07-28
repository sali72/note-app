from fastapi import Depends
from app.core.config import Settings
from app.core.deps.settings import get_settings
from app.core.services.email_service import EmailService
from app.core.services.jwt_service import JWTService
from app.core.services.password_service import PasswordService


def get_jwt_service(settings: Settings = Depends(get_settings)) -> JWTService:
    """Get JWT service with injected settings."""
    return JWTService(settings)


def get_password_service(settings: Settings = Depends(get_settings)) -> PasswordService:
    """Get password service with injected settings (uses 4 rounds in testing for speed)."""
    rounds = 4 if settings.environment == "testing" else settings.bcrypt_rounds
    return PasswordService(rounds=rounds)


def get_email_service(settings: Settings = Depends(get_settings)) -> EmailService:
    """Get email service with injected settings."""
    return EmailService(settings)
