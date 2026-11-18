from fastapi import FastAPI

from app.core import settings
from app.routers.organization import router as organization_router
from app.routers.user import router as user_router
from app.routers.zone import router as zone_router

# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     pass


app = FastAPI(
    root_path="/sendora/api",
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    openapi_tags=[{"name": ""}],
    docs_url=f"{settings.API_PREFIX}/docs",
    openapi_url=f"{settings.API_PREFIX}/openapi.json",
    # lifespan=lifespan
)

app.include_router(user_router, prefix=settings.API_PREFIX)
app.include_router(organization_router, prefix=settings.API_PREFIX)
app.include_router(zone_router, prefix=settings.API_PREFIX)
