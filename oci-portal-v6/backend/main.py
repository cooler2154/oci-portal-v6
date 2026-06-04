# backend/main.py
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from core.config import settings
from core.logging_setup import app_logger
from db.database import engine, AsyncSessionLocal, Base
from db.models import User
from routers.auth import hash_password
from routers import auth, users, instances, audit, debug, cache

BASE_DIR  = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    app_logger.info(f"Starting OCI Portal [{settings.APP_ENV}]")

    # Create all DB tables (safe — skips existing tables)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    app_logger.info("Database tables ready")

    # Seed default admin only when table is empty
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User))
        if not result.first():
            admin = User(
                name="Administrator",
                username="admin",
                email="admin@myorg.com",
                hashed_pw=hash_password("Admin1234!"),
                role="admin",
                scope="all",
                allowed_actions="",
                tag_filters="[]",
                active=True,
            )
            db.add(admin)
            await db.commit()
            app_logger.warning(
                "Seeded default admin → username=admin  password=Admin1234!"
                "  — CHANGE THIS PASSWORD IMMEDIATELY via User Management tab"
            )

    yield  # app running

    await engine.dispose()
    app_logger.info("OCI Portal shut down")


app = FastAPI(
    title="OCI Instance Portal",
    version="2.0.0",
    lifespan=lifespan,
    docs_url ="/docs"  if settings.APP_ENV != "production" else None,
    redoc_url="/redoc" if settings.APP_ENV != "production" else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(instances.router)
app.include_router(audit.router)
app.include_router(debug.router)
app.include_router(cache.router)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
@app.get("/{full_path:path}", response_class=HTMLResponse, include_in_schema=False)
async def serve_frontend(request: Request, full_path: str = ""):
    # Let FastAPI handle /api/* and /static/* — only intercept UI routes
    if full_path.startswith("api/") or full_path.startswith("static/"):
        raise HTTPException(404)
    return templates.TemplateResponse("index.html", {"request": request})
