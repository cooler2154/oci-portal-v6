# backend/routers/audit.py
import csv, io
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from db.models import AuditLog, Role, User
from models.schemas import AuditOut
from routers.auth import get_current_user

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("/users", response_model=List[str])
async def distinct_users(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role == Role.viewer:
        raise HTTPException(403, "Audit log requires Operator or Admin role")
    result = await db.execute(
        select(AuditLog.username).distinct().order_by(AuditLog.username)
    )
    return [r[0] for r in result.all()]


@router.get("", response_model=List[AuditOut])
async def get_audit_log(
    username:    Optional[str] = Query(None),
    action:      Optional[str] = Query(None),
    compartment: Optional[str] = Query(None),
    region:      Optional[str] = Query(None),
    q:           Optional[str] = Query(None),
    limit:       int           = Query(200, le=1000),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role == Role.viewer:
        raise HTTPException(403, "Audit log requires Operator or Admin role")

    # Operators only see their own audit entries
    if current_user.role == Role.operator:
        username = current_user.username

    stmt = select(AuditLog).order_by(AuditLog.timestamp.desc())
    if username:    stmt = stmt.where(AuditLog.username    == username)
    if action:      stmt = stmt.where(AuditLog.action      == action)
    if region:      stmt = stmt.where(AuditLog.region      == region)
    if compartment: stmt = stmt.where(AuditLog.compartment.contains(compartment))
    if q:           stmt = stmt.where(
        AuditLog.resource.contains(q) | AuditLog.username.contains(q)
    )

    result = await db.execute(stmt.limit(limit))
    return result.scalars().all()


@router.get("/export")
async def export_csv(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != Role.admin:
        raise HTTPException(403, "CSV export requires Admin role")
    result = await db.execute(
        select(AuditLog).order_by(AuditLog.timestamp.desc())
    )
    rows = result.scalars().all()
    out  = io.StringIO()
    w    = csv.writer(out)
    w.writerow(["timestamp","username","user_email","action",
                "resource","compartment","region","source_ip","detail"])
    for r in rows:
        w.writerow([r.timestamp, r.username, r.user_email or "",
                    r.action, r.resource, r.compartment,
                    r.region, r.source_ip, r.detail])
    out.seek(0)
    return StreamingResponse(
        iter([out.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_log.csv"},
    )
