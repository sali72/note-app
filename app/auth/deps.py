from fastapi import Depends, HTTPException, status, Request

from app.auth.config import AuthModuleConfig
from app.auth.db.models import User
from app.auth.db.repository import UserRepository
from app.auth.db.session_repository import SessionRepository
from app.auth.facade.auth_facade import AuthFacade
from app.auth.services.cookie_service import CookieService
from app.auth.services.token_blacklist import TokenBlacklistService
from app.auth.services.token_service import TokenService
from app.core.config import Settings
from app.core.deps.services import get_email_service, get_jwt_service, get_password_service
from app.core.deps.settings import get_settings
from app.core.services.email_service import EmailService
from app.core.services.jwt_service import JWTService
from app.core.services.password_service import PasswordService


def get_auth_config() -> AuthModuleConfig:
    return AuthModuleConfig()


def get_user_repository() -> UserRepository:
    return UserRepository()


def get_session_repository() -> SessionRepository:
    return SessionRepository()


def get_token_service(
    jwt_service: JWTService = Depends(get_jwt_service),
    config: AuthModuleConfig = Depends(get_auth_config),
) -> TokenService:
    return TokenService(jwt_service=jwt_service, config=config)


def get_cookie_service(
    settings: Settings = Depends(get_settings),
) -> CookieService:
    return CookieService(settings)


def get_token_blacklist(
    settings: Settings = Depends(get_settings),
) -> TokenBlacklistService:
    return TokenBlacklistService(settings.redis_url)


# ---------------------------------------------------------------------------
# Composite dependencies
# ---------------------------------------------------------------------------

def get_auth_facade(
    repository: UserRepository = Depends(get_user_repository),
    jwt_service: JWTService = Depends(get_jwt_service),
    password_service: PasswordService = Depends(get_password_service),
    email_service: EmailService = Depends(get_email_service),
    token_blacklist: TokenBlacklistService = Depends(get_token_blacklist),
    config: AuthModuleConfig = Depends(get_auth_config),
) -> AuthFacade:
    return AuthFacade(
        repository=repository,
        jwt_service=jwt_service,
        password_service=password_service,
        email_service=email_service,
        token_blacklist=token_blacklist,
        config=config,
    )


# ---------------------------------------------------------------------------
# Auth guards
# ---------------------------------------------------------------------------


async def get_current_user(
    request: Request,
    facade: AuthFacade = Depends(get_auth_facade),
) -> User:
    """Extract the authenticated user from the ``access_token`` HttpOnly cookie.

    Raises:
        HTTPException(401): No cookie or invalid / blacklisted token.
        HTTPException(403): Account is deactivated.
    """
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    user = await facade.verify_token(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated",
        )

    request.state.user = user
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated",
        )
    return current_user


async def get_current_admin_user(
    current_user: User = Depends(get_current_active_user),
) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have administrator privileges",
        )
    return current_user
