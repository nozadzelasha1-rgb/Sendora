import uuid

from pydantic import BaseModel, Field

from app.schema.user import UserRead


class TokenUser(BaseModel):
    """Identity extracted from a verified access token."""

    id: uuid.UUID
    username: str | None
    session_id: uuid.UUID


class TokenResponse(BaseModel):
    """Login/refresh response: access and refresh tokens and the user."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserRead


class RefreshRequest(BaseModel):
    """Body carrying a refresh token for /refresh (strict shape validation)."""

    refresh_token: str = Field(min_length=1, max_length=512)


class LogoutRequest(BaseModel):
    """Body for /logout: any string is accepted so logout never fails on shape."""

    refresh_token: str
