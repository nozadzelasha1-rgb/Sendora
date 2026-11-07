from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_connector import get_session
from app.funcs.user import User, UserAlreadyExistsError, UserNotFoundError
from app.schema.user import UserCreate, UserCredentials, UserRead

router = APIRouter(prefix='/users', tags=["User"])


@router.post(
    '',
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
    '/login',
    response_model=UserRead,
    status_code=status.HTTP_200_OK,
    summary="Log in",
    description=(
        "Check the credentials (password and exactly one of username, phone "
        "or email) and return the user. No token is issued yet."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Invalid credentials"},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error"},
    },
)
async def login_user(
    creds: UserCredentials,
    session: AsyncSession = Depends(get_session),
) -> UserRead:
    try:
        user = await User(session).get_by_credentials(creds)
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    return UserRead.model_validate(user)


@router.post(
    '/delete',
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a user",
    description=(
        "Permanently delete the user. Deletion is credential-confirmed: the "
        "request must carry the user's valid credentials."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Invalid credentials"},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error"},
    },
)
async def delete_user(
    creds: UserCredentials,
    session: AsyncSession = Depends(get_session),
) -> Response:
    try:
        await User(session).delete_with_credentials(creds)
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
