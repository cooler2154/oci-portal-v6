# backend/routers/debug.py
# ---------------------------------------------------------------
# Debug console endpoint — admin only.
#
# GET /api/debug/logs   stream last N lines of debug.log as JSON
# GET /api/debug/health simple health check
# ---------------------------------------------------------------

from fastapi import APIRouter, Depends, Query
from fastapi import HTTPException
from pathlib import Path

from core.config import settings
from db.models import Role, User
from routers.auth import get_current_user

router = APIRouter(prefix="/api/debug", tags=["debug"])


@router.get("/health")
async def health():
    """
    Load-balancer health check — no auth required.
    Returns 200 with status info.
    """
    return {"status": "ok", "env": settings.APP_ENV}


@router.get("/logs")
async def get_logs(
    lines: int = Query(200, le=1000, description="Number of recent log lines to return"),
    level: str = Query(None,  description="Filter by level: DEBUG|INFO|WARN|ERROR"),
    module: str = Query(None, description="Filter by module name"),
    q: str     = Query(None,  description="Free-text search"),
    current_user: User = Depends(get_current_user),
):
    """
    Return recent structured log entries from debug.log.
    Admin only — logs can expose internal details.
    """
    if current_user.role != Role.admin:
        raise HTTPException(403, "Debug log requires Admin role")

    log_path = Path(settings.LOG_FILE)
    if not log_path.exists():
        return []

    raw_lines = log_path.read_text(errors="replace").splitlines()
    recent = raw_lines[-lines:]   # last N lines

    parsed = []
    for line in reversed(recent):
        # Expected format: "HH:MM:SS.mmm LEVEL [module       ] message"
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        ts, lv, mod, msg = parts[0], parts[1], parts[2], parts[3]
        mod = mod.strip("[]")

        # Apply filters
        if level  and lv  != level:  continue
        if module and module not in mod: continue
        if q      and q.lower() not in msg.lower(): continue

        parsed.append({"ts": ts, "level": lv, "module": mod, "msg": msg})

    return parsed
