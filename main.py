from starlette.middleware.cors import CORSMiddleware
from app.routers import app
from app.core import settings

app.add_middleware(
    CORSMiddleware,
    allow_credentials=False,
    allow_origins=settings.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=True)
