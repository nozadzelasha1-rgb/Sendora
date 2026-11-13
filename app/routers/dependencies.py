from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_connector import get_session
from app.funcs.auth import Auth, InvalidTokenError, TokenExpiredError
from app.schema.user import UserRead

bearer_scheme = HTTPBearer(auto_error=False)

INVALID_TOKEN_DETAIL = "Invalid authentication credentials"
EXPIRED_TOKEN_DETAIL = "Authentication expired, please sign in again"
_AUTH_HEADERS = {"WWW-Authenticate": "Bearer"}


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> UserRead:
    """Resolve the active user from the Bearer token or raise 401."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=INVALID_TOKEN_DETAIL,
            headers=_AUTH_HEADERS,
        )
    try:
        user = await Auth(session).get_user_from_token(credentials.credentials)
    except TokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=EXPIRED_TOKEN_DETAIL,
            headers=_AUTH_HEADERS,
        )
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=INVALID_TOKEN_DETAIL,
            headers=_AUTH_HEADERS,
        )
    return UserRead.model_validate(user)
