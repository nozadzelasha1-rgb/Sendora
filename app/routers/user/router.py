from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings
from app.core.db_connector import get_session
from app.funcs.auth import Auth, RefreshRetryError, RefreshTokenError
from app.funcs.user import User, UserAlreadyExistsError, UserNotFoundError
from app.routers.dependencies import get_current_user
from app.schema.auth import LogoutRequest, RefreshRequest, TokenResponse
from app.schema.user import UserCreate, UserCredentials, UserRead

router = APIRouter(prefix="/users", tags=["User"])

_AUTH_HEADERS = {"WWW-Authenticate": "Bearer"}
_INVALID_CREDENTIALS_DETAIL = "Invalid credentials"
_INVALID_TOKEN_DETAIL = "Invalid authentication credentials"
_REFRESH_RETRY_DETAIL = "Refresh in progress, please try again"
_NO_STORE_HEADERS = {"Cache-Control": "no-store"}


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user",
    description="Create a user with a unique username, phone or email.",
    responses={
        status.HTTP_409_CONFLICT: {"description": "User already exists"},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error"},
    },
)
async def create_user(
    data: UserCreate,
    session: AsyncSession = Depends(get_session),
) -> UserRead:
    try:
        user = await User(session).create(data)
    except UserAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User already exists",
        )
    return UserRead.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Log in",
    description=(
        "Check the credentials (password and exactly one of username, phone "
        "or email) and return a Bearer access token with the user."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Invalid credentials"},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error"},
    },
)
async def login_user(
    creds: UserCredentials,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    try:
        result = await Auth(session).login(creds)
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_INVALID_CREDENTIALS_DETAIL,
        )
    response.headers.update(_NO_STORE_HEADERS)
    return TokenResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserRead.model_validate(result.user),
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Refresh tokens",
    description=(
        "Exchange a refresh token for a new access token and a new refresh "
        "token. The presented refresh token is invalidated."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Invalid or expired authentication credentials"
        },
        status.HTTP_409_CONFLICT: {"description": "Refresh in progress"},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error"},
    },
)
async def refresh_tokens(
    data: RefreshRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    try:
        result = await Auth(session).refresh(data.refresh_token)
    except RefreshTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_INVALID_TOKEN_DETAIL,
            headers=_AUTH_HEADERS,
        )
    except RefreshRetryError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_REFRESH_RETRY_DETAIL,
        )
    response.headers.update(_NO_STORE_HEADERS)
    return TokenResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserRead.model_validate(result.user),
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Log out",
    description=(
        "Revoke the session of the refresh token. Always returns 204 for a "
        "well-formed JSON body, whatever the token string is, and does not "
        "reveal whether the token existed. A missing refresh_token field is "
        "rejected with 422."
    ),
    responses={
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error"},
    },
)
async def logout_user(
    data: LogoutRequest,
    session: AsyncSession = Depends(get_session),
) -> Response:
    await Auth(session).logout(data.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/logout-all",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Log out everywhere",
    description="Revoke all sessions of the user identified by the Bearer token.",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Invalid or expired authentication credentials"
        },
    },
)
async def logout_all_sessions(
    current_user: UserRead = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await Auth(session).logout_all(current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/me",
    response_model=UserRead,
    status_code=status.HTTP_200_OK,
    summary="Get the current user",
    description="Return the user identified by the Bearer access token.",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Invalid or expired authentication credentials"
        },
    },
)
async def get_me(current_user: UserRead = Depends(get_current_user)) -> UserRead:
    return current_user


@router.post(
    "/delete",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a user",
    description=(
        "Permanently delete the user. Requires a Bearer access token and is "
        "credential-confirmed: the body must carry the token user's valid "
        "credentials."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": (
                "Invalid credentials or invalid/expired authentication credentials"
            )
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error"},
    },
)
async def delete_user(
    creds: UserCredentials,
    current_user: UserRead = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    try:
        await User(session).delete_user_with_credentials(creds, current_user.id)
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_INVALID_CREDENTIALS_DETAIL,
            headers=_AUTH_HEADERS,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
