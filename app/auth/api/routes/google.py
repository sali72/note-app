from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import AnyUrl

from app.auth.api.config import AuthRoutes
from app.auth.deps import get_auth_facade, get_cookie_service
from app.auth.facade.auth_facade import AuthFacade
from app.auth.services.cookie_service import CookieService
from app.auth.services.google_oauth_service import GoogleOAuthService
from app.core.config import Settings
from app.core.deps.settings import get_settings
from app.core.logging import get_logger
from app.core.rate_limit import limiter
from app.core.deps.services import get_jwt_service
from app.core.services.jwt_service import JWTService

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["google-auth"])


def get_google_oauth_service(
    settings: Settings = Depends(get_settings),
    jwt_service: JWTService = Depends(get_jwt_service),
) -> GoogleOAuthService:
    return GoogleOAuthService(settings, jwt_service.secret_key)


@router.get(AuthRoutes.GOOGLE_LOGIN, summary="Sign in with Google")
@limiter.limit("5/minute")
async def google_login(
    request: Request,
    google_oauth: GoogleOAuthService = Depends(get_google_oauth_service),
):
    """Redirect the browser to Google's OAuth consent screen."""
    state = google_oauth.generate_state()
    authorization_url = google_oauth.get_authorization_url(state)
    return RedirectResponse(url=authorization_url)


@router.get(
    AuthRoutes.GOOGLE_CALLBACK,
    summary="Google OAuth callback",
    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
)
@limiter.limit("5/minute")
async def google_callback(
    code: str,
    state: str,
    request: Request,
    google_oauth: GoogleOAuthService = Depends(get_google_oauth_service),
    facade: AuthFacade = Depends(get_auth_facade),
    cookie_service: CookieService = Depends(get_cookie_service),
    settings: Settings = Depends(get_settings),
):
    """Handle the redirect back from Google after user consent.

    1. Validate the ``state`` parameter (CSRF protection).
    2. Exchange the authorisation ``code`` for Google tokens.
    3. Look up the user's profile from Google.
    4. Find or create a local user account (linking by email if needed).
    5. Issue our own JWT and set it as an HttpOnly cookie.
    6. Redirect the browser back to the frontend.
    """
    # 1 – Validate state
    if not google_oauth.validate_state(state):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid state parameter",
        )

    try:
        # 2 – Exchange code
        tokens = await google_oauth.exchange_code(code)

        # 3 – Get user info
        google_user = await google_oauth.get_user_info(tokens.access_token)

        if not google_user.email_verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google email is not verified",
            )

        # 4 – Find or create
        user = await facade.find_or_create_google_user(
            google_id=google_user.sub,
            email=google_user.email,
        )

        # 5 – Issue access and refresh tokens
        access_token, refresh_token = await facade.create_session_tokens(user)

        # 6 – Set cookies + redirect
        redirect = RedirectResponse(url=settings.frontend_url)
        cookie_service.set_auth_cookie(redirect, access_token)
        cookie_service.set_refresh_cookie(redirect, refresh_token)
        cookie_service.set_session_cookie(redirect)
        return redirect

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("google_callback_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google authentication failed",
        )
