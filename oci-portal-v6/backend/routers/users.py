# backend/routers/users.py
import json
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging_setup import app_logger, audit_logger
from db.database import get_db
from db.models import AuditLog, User
from models.schemas import UserCreate, UserOut, UserUpdate
from routers.auth import hash_password, require_admin

router = APIRouter(prefix="/api/users", tags=["users"])


async def _get_or_404(uid: int, db: AsyncSession) -> User:
    user = await db.get(User, uid)
    if not user:
        raise HTTPException(404, "User not found")
    return user


async def _write_audit(db, actor: User, action: str, resource: str,
                        detail: str = "", ip: str = ""):
    db.add(AuditLog(
        username=actor.username,
        user_email=actor.email,
        action=action,
        resource=resource,
        detail=detail,
        source_ip=ip,
    ))
    await db.commit()
    audit_logger.info(
        f"user={actor.username} action={action} resource={resource} ip={ip}"
    )


@router.get("", response_model=List[UserOut])
async def list_users(
    admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).order_by(User.created_at))
    return result.scalars().all()


@router.post("", response_model=UserOut, status_code=201)
async def create_user(
    body:   UserCreate,
    request: Request,
    admin:  User = Depends(require_admin),
    db:     AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none():
        raise HTTPException(400, f"Username '{body.username}' is already taken")

    # Serialise tag_filters list → JSON string for storage
    tag_json = json.dumps([f.model_dump() for f in body.tag_filters])

    new_user = User(
        name=body.name,
        username=body.username,
        email=body.email or None,
        hashed_pw=hash_password(body.password),
        role=body.role,
        scope=body.scope,
        allowed_actions=body.allowed_actions or "",
        tag_filters=tag_json,
    )
    db.add(new_user)
    await db.flush()
    await db.refresh(new_user)

    await _write_audit(
        db, admin, "CREATE_USER", body.username,
        detail=f"role={body.role} scope={body.scope} tags={tag_json}",
        ip=request.client.host,
    )
    app_logger.info(f"User '{body.username}' created by {admin.username}")
    return new_user


@router.patch("/{uid}", response_model=UserOut)
async def update_user(
    uid:    int,
    body:   UserUpdate,
    request: Request,
    admin:  User = Depends(require_admin),
    db:     AsyncSession = Depends(get_db),
):
    user    = await _get_or_404(uid, db)
    changes = body.model_dump(exclude_none=True)

    if body.name            is not None: user.name            = body.name
    if body.email           is not None: user.email           = body.email or None
    if body.role            is not None: user.role            = body.role
    if body.scope           is not None: user.scope           = body.scope
    if body.allowed_actions is not None: user.allowed_actions = body.allowed_actions
    if body.active          is not None: user.active          = body.active
    if body.tag_filters     is not None:
        user.tag_filters = json.dumps([f.model_dump() for f in body.tag_filters])
        changes["tag_filters"] = user.tag_filters
    if body.password is not None:
        if len(body.password) < 8:
            raise HTTPException(400, "Password must be at least 8 characters")
        user.hashed_pw = hash_password(body.password)
        changes.pop("password", None)

    await db.commit()
    await db.refresh(user)

    await _write_audit(
        db, admin, "UPDATE_USER", user.username,
        detail=str(changes), ip=request.client.host,
    )
    app_logger.info(f"User '{user.username}' updated by {admin.username}")
    return user


@router.delete("/{uid}", status_code=204)
async def delete_user(
    uid:    int,
    request: Request,
    admin:  User = Depends(require_admin),
    db:     AsyncSession = Depends(get_db),
):
    user = await _get_or_404(uid, db)
    if user.username == admin.username:
        raise HTTPException(400, "You cannot delete your own account")
    uname = user.username
    await db.delete(user)
    db.add(AuditLog(
        username=admin.username,
        user_email=admin.email,
        action="DELETE_USER",
        resource=uname,
        source_ip=request.client.host,
    ))
    await db.commit()
    audit_logger.info(
        f"user={admin.username} action=DELETE_USER resource={uname}"
    )
    app_logger.info(f"User '{uname}' deleted by {admin.username}")
