from fastapi import APIRouter, HTTPException, status, Depends, Request, Response

from app.auth.api.schemas.request import RegisterRequest, LoginRequest, ResendVerificationRequest, ResetPasswordRequest, UpdatePreferencesRequest
from app.auth.api.schemas.response import (
    UserResponse,
    LoginResponse,
    MessageResponse
)
from app.auth.api.config import AuthRoutes
from app.auth.deps import get_auth_facade, get_cookie_service
from app.auth.facade.auth_facade import AuthFacade
from app.auth.services.cookie_service import CookieService
from app.auth.db.models import User
from app.auth.deps import get_current_user
from app.core.rate_limit import limiter


# Router prefix is set in main.py, routes here are relative to /auth
router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post(
    AuthRoutes.REGISTER,
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
@limiter.limit("5/minute")
async def register(
    request: Request,
    register_request: RegisterRequest,
    facade: AuthFacade = Depends(get_auth_facade)
) -> MessageResponse:
    """
    Register a new user account.
    
    - **email**: Valid email address (required)
    - **password**: Password (min 8 characters, required)
    - **confirm_password**: Password confirmation (must match password)
    """
    try:
        # Validate passwords match
        register_request.validate_passwords_match()
        
        # Register user
        await facade.register(
            email=register_request.email,
            password=register_request.password
        )
        
        return MessageResponse(
            message="Registration successful. Please check your email to verify your account."
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post(
    AuthRoutes.LOGIN,
    response_model=LoginResponse,
    summary="Login user",
)
@limiter.limit("5/minute")
async def login(
    request: Request,
    login_request: LoginRequest,
    facade: AuthFacade = Depends(get_auth_facade),
    cookie_service: CookieService = Depends(get_cookie_service),
    response: Response = None,
) -> LoginResponse:
    """
    Authenticate user and receive access token.
    
    - **email**: User email address
    - **password**: User password
    
    Sets an HttpOnly ``access_token`` cookie on success.
    The response body still contains the token for API clients.
    """
    try:
        access_token, refresh_token, user = await facade.login(
            email=login_request.email,
            password=login_request.password
        )
        
        cookie_service.set_auth_cookie(response, access_token)
        cookie_service.set_refresh_cookie(response, refresh_token)
        cookie_service.set_session_cookie(response)
        return LoginResponse(
            access_token=access_token,
            token_type="bearer",
            user=UserResponse.from_document(user)
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )


@router.post(
    "/refresh",
    response_model=LoginResponse,
    summary="Refresh access token using HTTP-only refresh token cookie",
)
async def refresh(
    request: Request,
    response: Response,
    facade: AuthFacade = Depends(get_auth_facade),
    cookie_service: CookieService = Depends(get_cookie_service),
) -> LoginResponse:
    """
    Issue a new short-lived access token and rotated refresh token using the refresh_token cookie.
    """
    raw_refresh_token = request.cookies.get("refresh_token")
    if not raw_refresh_token:
        cookie_service.clear_all_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing",
        )

    try:
        new_access_token, new_refresh_token, user = await facade.refresh_access_token(
            raw_refresh_token
        )
        cookie_service.set_auth_cookie(response, new_access_token)
        cookie_service.set_refresh_cookie(response, new_refresh_token)
        cookie_service.set_session_cookie(response)
        return LoginResponse(
            access_token=new_access_token,
            token_type="bearer",
            user=UserResponse.from_document(user),
        )
    except ValueError as e:
        cookie_service.clear_all_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )


@router.get(
    AuthRoutes.ME,
    response_model=UserResponse,
    summary="Get current user"
)
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
) -> UserResponse:
    """
    Get current authenticated user information.
    
    Requires valid JWT token in Authorization header.
    """
    return UserResponse.from_document(current_user)


@router.get(
    AuthRoutes.VERIFY_EMAIL,
    response_model=MessageResponse,
    summary="Verify email address"
)
async def verify_email(
    token: str,
    facade: AuthFacade = Depends(get_auth_facade)
) -> MessageResponse:
    """
    Verify email address using verification token.

    - **token**: Verification token sent to user's email
    """
    try:
        await facade.verify_email(token)
        return MessageResponse(
            message="Email verified successfully"
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post(
    AuthRoutes.RESEND_VERIFICATION,
    response_model=MessageResponse,
    summary="Resend verification email"
)
@limiter.limit("3/minute")
async def resend_verification(
    request: Request,
    resend_request: ResendVerificationRequest,
    facade: AuthFacade = Depends(get_auth_facade)
) -> MessageResponse:
    """
    Resend email verification link.

    - **email**: User email address
    """
    try:
        await facade.resend_verification(resend_request.email)
        return MessageResponse(
            message="Verification email sent"
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post(
    AuthRoutes.RESET_PASSWORD,
    response_model=MessageResponse,
    summary="Request password reset"
)
@limiter.limit("5/minute")
async def reset_password(
    request: Request,
    reset_request: ResetPasswordRequest,
    facade: AuthFacade = Depends(get_auth_facade)
) -> MessageResponse:
    """
    Request password reset email.

    - **email**: User email address

    Note: Always returns success to prevent email enumeration.
    """
    await facade.reset_password(reset_request.email)

    return MessageResponse(
        message="If an account with this email exists, a password reset link has been sent."
    )


@router.post(
    AuthRoutes.LOGOUT,
    response_model=MessageResponse,
    summary="Logout user",
)
async def logout(
    request: Request,
    facade: AuthFacade = Depends(get_auth_facade),
    cookie_service: CookieService = Depends(get_cookie_service),
    response: Response = None,
) -> MessageResponse:
    """
    Logout the current user by blacklisting their access token, revoking their refresh token, and clearing cookies.
    """
    access_token = request.cookies.get("access_token")
    refresh_token = request.cookies.get("refresh_token")
    await facade.logout(token=access_token, raw_refresh_token=refresh_token)

    cookie_service.clear_all_cookies(response)
    return MessageResponse(message="Logged out successfully")


@router.get(
    AuthRoutes.VERIFY,
    response_model=UserResponse,
    summary="Verify JWT token"
)
async def verify_token(
    current_user: User = Depends(get_current_user)
) -> UserResponse:
    """
    Verify JWT token and return user information.
    
    Requires valid JWT token in Authorization header.
    """
    return UserResponse.from_document(current_user)


@router.put(
    AuthRoutes.PREFERENCES,
    response_model=UserResponse,
    summary="Update user preferences"
)
async def update_preferences(
    request: UpdatePreferencesRequest,
    current_user: User = Depends(get_current_user),
    facade: AuthFacade = Depends(get_auth_facade)
) -> UserResponse:
    """
    Update current user's preferences (partial update).
    
    Only provided fields will be updated; omitted fields retain their current values.
    """
    preferences = request.model_dump(exclude_none=True)
    user = await facade.update_preferences(str(current_user.id), preferences)
    return UserResponse.from_document(user)
