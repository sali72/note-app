from datetime import timedelta
from fastapi import Response

from app.core.config import Settings


class CookieService:
    """Manage HttpOnly auth cookies and non-HttpOnly session indicator.

    - access_token: HttpOnly cookie containing short-lived JWT (15 mins), scoped to /api/v0.
    - refresh_token: HttpOnly cookie containing long-lived refresh token (30 days), scoped strictly to /api/v0/auth/refresh.
    - session_exists: non-HttpOnly session indicator cookie (30 days) for JS to check state without API calls.
    """

    def __init__(self, settings: Settings):
        self.secure = settings.is_production
        self.samesite = "lax"
        self.api_path = "/api/v0"
        self.refresh_path = "/api/v0/auth/refresh"
        self.root_path = "/"
        self.access_token_max_age = int(timedelta(minutes=15).total_seconds())
        self.refresh_token_max_age = int(timedelta(days=30).total_seconds())

    # ------------------------------------------------------------------
    # Access token cookie (HttpOnly — short lived)
    # ------------------------------------------------------------------

    def set_auth_cookie(
        self, response: Response, token: str, max_age: int | None = None
    ) -> None:
        response.set_cookie(
            key="access_token",
            value=token,
            httponly=True,
            secure=self.secure,
            samesite=self.samesite,
            max_age=max_age if max_age is not None else self.access_token_max_age,
            path=self.api_path,
        )

    def clear_auth_cookie(self, response: Response) -> None:
        response.delete_cookie(key="access_token", path=self.api_path)

    # ------------------------------------------------------------------
    # Refresh token cookie (HttpOnly — long lived, narrow path)
    # ------------------------------------------------------------------

    def set_refresh_cookie(
        self, response: Response, token: str, max_age: int | None = None
    ) -> None:
        response.set_cookie(
            key="refresh_token",
            value=token,
            httponly=True,
            secure=self.secure,
            samesite=self.samesite,
            max_age=max_age if max_age is not None else self.refresh_token_max_age,
            path=self.refresh_path,
        )

    def clear_refresh_cookie(self, response: Response) -> None:
        response.delete_cookie(key="refresh_token", path=self.refresh_path)

    # ------------------------------------------------------------------
    # Session indicator (non-HttpOnly — JS can read it)
    # ------------------------------------------------------------------

    def set_session_cookie(self, response: Response, max_age: int | None = None) -> None:
        response.set_cookie(
            key="session_exists",
            value="1",
            httponly=False,
            secure=self.secure,
            samesite=self.samesite,
            max_age=max_age if max_age is not None else self.refresh_token_max_age,
            path=self.root_path,
        )

    def clear_session_cookie(self, response: Response) -> None:
        response.delete_cookie(key="session_exists", path=self.root_path)

    def clear_all_cookies(self, response: Response) -> None:
        self.clear_auth_cookie(response)
        self.clear_refresh_cookie(response)
        self.clear_session_cookie(response)

