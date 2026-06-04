# backend/models/schemas.py
from __future__ import annotations
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, field_validator
from db.models import Role, ActionType


class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    role:         str
    name:         str
    username:     str


# ── Users ─────────────────────────────────────────────────────────

class TagFilter(BaseModel):
    """Single OCI tag matcher applied to instances."""
    namespace: Optional[str] = None   # e.g. "Oracle-Tags" or custom ns
    key:       str                    # tag key
    value:     str                    # tag value (exact match)


class UserCreate(BaseModel):
    name:            str
    username:        str
    email:           Optional[str] = None
    password:        str
    role:            Role = Role.viewer
    scope:           str  = "all"
    allowed_actions: str  = ""
    tag_filters:     List[TagFilter] = []

    @field_validator("password")
    @classmethod
    def pw_min_length(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

    @field_validator("username")
    @classmethod
    def uname_clean(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Username is required")
        if " " in v:
            raise ValueError("Username must not contain spaces")
        return v


class UserUpdate(BaseModel):
    name:            Optional[str]        = None
    email:           Optional[str]        = None
    role:            Optional[Role]       = None
    scope:           Optional[str]        = None
    allowed_actions: Optional[str]        = None
    tag_filters:     Optional[List[TagFilter]] = None
    active:          Optional[bool]       = None
    password:        Optional[str]        = None


class UserOut(BaseModel):
    id:              int
    name:            str
    username:        str
    email:           Optional[str]
    role:            Role
    scope:           str
    allowed_actions: str
    tag_filters:     str     # raw JSON stored in DB
    active:          bool
    created_at:      datetime
    model_config = {"from_attributes": True}


# ── Instances ──────────────────────────────────────────────────────

class InstanceOut(BaseModel):
    id:             str
    name:           str
    status:         str
    shape:          str
    region:         str
    compartment_id: str
    vcpus:          Optional[int]   = None
    ram_gb:         Optional[float] = None
    freeform_tags:  Dict[str, str]  = {}
    defined_tags:   Dict[str, Any]  = {}


class ActionRequest(BaseModel):
    action: ActionType


# ── Compartments ───────────────────────────────────────────────────

class CompartmentOut(BaseModel):
    id:          str
    name:        str
    description: Optional[str] = None


# ── Audit ──────────────────────────────────────────────────────────

class AuditOut(BaseModel):
    id:          int
    timestamp:   datetime
    username:    str
    user_email:  Optional[str]
    action:      str
    resource:    str
    compartment: str
    region:      str
    source_ip:   str
    detail:      str
    model_config = {"from_attributes": True}
