# backend/db/models.py
# ──────────────────────────────────────────────────────────────────
# Database models.
# Key additions vs previous version:
#   • tag_filters  — JSON list of OCI tag matchers, e.g.
#                    [{"key":"Environment","value":"prod"},
#                     {"namespace":"ops","key":"team","value":"infra"}]
#                    Empty = no tag restriction.
#   • scope        — comma-separated compartment OCIDs or "all"
#   • allowed_actions — comma-separated START,STOP,SOFTRESET or ""
# ──────────────────────────────────────────────────────────────────
import enum
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Enum, Integer, String, Text
from db.database import Base


class Role(str, enum.Enum):
    admin    = "admin"
    operator = "operator"
    viewer   = "viewer"


class ActionType(str, enum.Enum):
    START     = "START"
    STOP      = "STOP"
    SOFTRESET = "SOFTRESET"


class User(Base):
    __tablename__ = "users"

    id              = Column(Integer, primary_key=True, index=True)
    name            = Column(String(120), nullable=False)
    username        = Column(String(120), unique=True, index=True, nullable=False)
    email           = Column(String(255), nullable=True)
    hashed_pw       = Column(String(255), nullable=False)
    role            = Column(Enum(Role), default=Role.viewer, nullable=False)

    # Compartment scope: "all"  OR  comma-sep OCIDs
    scope           = Column(Text, default="all", nullable=False)

    # Allowed actions: ""  = role default,  "START,STOP" = only those
    allowed_actions = Column(Text, default="", nullable=False)

    # OCI Tag filters (JSON): [] = no filter
    # e.g. '[{"namespace":"ops","key":"env","value":"dev"}]'
    tag_filters     = Column(Text, default="[]", nullable=False)

    active          = Column(Boolean, default=True, nullable=False)
    created_at      = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<User {self.username} role={self.role}>"


class AuditLog(Base):
    __tablename__ = "audit_log"

    id          = Column(Integer, primary_key=True, index=True)
    timestamp   = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    username    = Column(String(120), nullable=False, index=True)
    user_email  = Column(String(255), nullable=True)
    action      = Column(String(50),  nullable=False, index=True)
    resource    = Column(String(255), nullable=False)
    compartment = Column(String(255), default="")
    region      = Column(String(80),  default="")
    source_ip   = Column(String(50),  default="")
    detail      = Column(String(512), default="")

    def __repr__(self):
        return f"<AuditLog {self.timestamp} {self.username} {self.action}>"
