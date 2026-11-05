from fastapi import APIRouter
from fastapi.params import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_connector import get_session
from app.db_entities.users.user import UserDB

router = APIRouter(prefix='/users', tags=["User"])


@router.get('/users')
async def get_all_users(session: AsyncSession = Depends(get_session)):
    all_users = await session.execute(select(UserDB))
    print(all_users.all())
