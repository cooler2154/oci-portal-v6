# backend/routers/auth.py
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.logging_setup import app_logger, audit_logger
from db.database import get_db
from db.models import AuditLog, Role, User
from models.schemas import TokenResponse, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])

pwd_context  = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
ALGORITHM    = "HS256"


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_access_token(data: dict) -> str:
    payload = data.copy()
    payload["exp"] = datetime.utcnow() + timedelta(hours=settings.ACCESS_TOKEN_EXPIRE_HOURS)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


# ── Dependencies ─────────────────────────────────────────────────

async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: AsyncSession = Depends(get_db),
) -> User:
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if not username:
            raise exc
    except JWTError as e:
        app_logger.warning(f"JWT decode failed: {e}")
        raise exc

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None:
        raise exc
    if not user.active:
        raise HTTPException(status_code=403, detail="Account is deactivated")
    return user


async def require_admin(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    if current_user.role != Role.admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


async def require_operator(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    if current_user.role == Role.viewer:
        raise HTTPException(status_code=403, detail="Operator or Admin access required")
    return current_user


# ── Endpoints ────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """Login with username (not email) + password."""
    result = await db.execute(select(User).where(User.username == form_data.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.hashed_pw):
        app_logger.warning(f"Failed login: '{form_data.username}' from {request.client.host}")
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    if not user.active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    token = create_access_token({
        "sub":   user.username,
        "role":  user.role,
        "scope": user.scope,
    })

    # Write LOGIN to audit table
    db.add(AuditLog(
        username=user.username,
        user_email=user.email,
        action="LOGIN",
        resource="portal",
        source_ip=request.client.host,
    ))
    await db.commit()

    audit_logger.info(f"user={user.username} action=LOGIN ip={request.client.host}")
    app_logger.info(f"Login success: {user.username} role={user.role}")

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        role=user.role,
        name=user.name,
        username=user.username,
    )


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return current_user
