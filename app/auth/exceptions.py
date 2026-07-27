class AuthException(ValueError):
    """Base exception for authentication module."""
    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)


class InvalidCredentialsError(AuthException):
    """Raised when authentication credentials (email/password) are invalid."""
    pass


class TokenRevokedError(AuthException):
    """Raised when a refresh token or session family has been revoked."""
    pass


class InvalidTokenError(AuthException):
    """Raised when a token is invalid, expired, or malformed."""
    pass


class UserAlreadyExistsError(AuthException):
    """Raised when registering an email that is already registered."""
    pass


class SessionNotFoundError(AuthException):
    """Raised when a requested session family ID is not found."""
    pass
