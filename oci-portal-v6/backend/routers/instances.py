# backend/routers/instances.py
# ──────────────────────────────────────────────────────────────────
# Key fixes in this version:
#
# 1. REGION-SCOPED CLIENTS
#    Each API call creates a client for the requested region so OCI
#    returns instances *only* from that region.
#
# 2. COMPARTMENT SECURITY ENFORCEMENT
#    list_compartments: operators only see their scoped compartments.
#    list_instances:    operators only see instances in their scoped
#                       compartments. Instances in other compartments
#                       are filtered out server-side.
#
# 3. OCI TAG FILTERING
#    Operators with tag_filters only see/act on instances whose OCI
#    tags match ALL their tag rules (freeform or defined tags).
#
# 4. ACTION PERMISSION CHECK
#    Operators are limited to their allowed_actions list.
# ──────────────────────────────────────────────────────────────────
import json
from datetime import datetime
from typing import List, Optional

import oci
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.logging_setup import app_logger, audit_logger
from core.oci_client import (get_compute_client, get_identity_client,
                              get_base_config, identity_client)
from db.database import get_db
from db.models import AuditLog, Role, User
from models.schemas import ActionRequest, CompartmentOut, InstanceOut
from routers.auth import get_current_user, require_operator

router = APIRouter(prefix="/api", tags=["instances"])

# ── OCI region catalogue ──────────────────────────────────────────
OCI_REGIONS = [
    {"key": "ap-sydney-1",       "name": "Australia East (Sydney)"},
    {"key": "ap-melbourne-1",    "name": "Australia Southeast (Melbourne)"},
    {"key": "us-ashburn-1",      "name": "US East (Ashburn)"},
    {"key": "us-phoenix-1",      "name": "US West (Phoenix)"},
    {"key": "us-chicago-1",      "name": "US Midwest (Chicago)"},
    {"key": "eu-frankfurt-1",    "name": "Germany Central (Frankfurt)"},
    {"key": "eu-amsterdam-1",    "name": "Netherlands Northwest (Amsterdam)"},
    {"key": "eu-london-1",       "name": "UK South (London)"},
    {"key": "ap-tokyo-1",        "name": "Japan East (Tokyo)"},
    {"key": "ap-osaka-1",        "name": "Japan Central (Osaka)"},
    {"key": "ap-singapore-1",    "name": "Singapore"},
    {"key": "ap-mumbai-1",       "name": "India West (Mumbai)"},
    {"key": "ap-hyderabad-1",    "name": "India South (Hyderabad)"},
    {"key": "ap-seoul-1",        "name": "South Korea Central (Seoul)"},
    {"key": "ca-toronto-1",      "name": "Canada Southeast (Toronto)"},
    {"key": "ca-montreal-1",     "name": "Canada Southeast (Montreal)"},
    {"key": "sa-saopaulo-1",     "name": "Brazil East (São Paulo)"},
    {"key": "me-dubai-1",        "name": "UAE East (Dubai)"},
    {"key": "me-jeddah-1",       "name": "Saudi Arabia West (Jeddah)"},
    {"key": "af-johannesburg-1", "name": "South Africa Central (Johannesburg)"},
    {"key": "il-jerusalem-1",    "name": "Israel Central (Jerusalem)"},
]


# ── Tag matching helpers ──────────────────────────────────────────

def _parse_tag_filters(user: User) -> list:
    """Parse a user's tag_filters JSON into a list of dicts."""
    raw = (user.tag_filters or "[]").strip()
    if not raw or raw == "[]":
        return []
    try:
        return json.loads(raw)
    except Exception:
        return []


def _instance_matches_tags(instance, tag_filters: list) -> bool:
    """
    Return True if the instance satisfies ALL tag rules.
    Each rule: {"namespace": optional/null, "key": str, "value": str}
      - No namespace (None or "")  → freeform_tags match (case-insensitive key)
      - With namespace              → defined_tags[namespace][key] match (case-insensitive key)

    BUG FIXES:
      1. namespace stored as JSON null → Python None; must use (val or "") not .get("ns","").strip()
         because dict.get(key, default) only uses default when KEY IS MISSING,
         not when key exists with value None.
      2. Tag keys are matched case-insensitively so "environment" matches "Environment".
    """
    if not tag_filters:
        return True   # no restriction

    freeform = instance.freeform_tags or {}
    defined  = instance.defined_tags  or {}

    # Build case-insensitive lookup maps once
    freeform_lower = {k.lower(): v for k, v in freeform.items()}
    defined_lower  = {
        ns_key.lower(): {k.lower(): v for k, v in ns_vals.items()}
        for ns_key, ns_vals in defined.items()
        if isinstance(ns_vals, dict)
    }

    for rule in tag_filters:
        # FIX 1: use (x or "") to handle None correctly
        ns    = (rule.get("namespace") or "").strip()
        key   = (rule.get("key")       or "").strip()
        value = (rule.get("value")     or "").strip()

        if not key:
            continue  # skip incomplete rules

        # FIX 2: case-insensitive matching
        key_lower = key.lower()
        ns_lower  = ns.lower()

        if ns:
            # Defined tag: defined_tags[namespace][key] == value (case-insensitive keys)
            ns_tags = defined_lower.get(ns_lower, {})
            actual  = ns_tags.get(key_lower)
            if actual != value:
                return False
        else:
            # Freeform tag: freeform_tags[key] == value (case-insensitive key)
            actual = freeform_lower.get(key_lower)
            if actual != value:
                return False

    return True


# ── Scope helpers ─────────────────────────────────────────────────

def _user_allowed_compartments(user: User) -> Optional[List[str]]:
    """None = all compartments. List = allowed OCIDs."""
    if user.role == Role.admin:
        return None
    if user.scope == "all":
        return None
    return [s.strip() for s in user.scope.split(",") if s.strip()]


def _compartment_allowed(user: User, compartment_id: str) -> bool:
    allowed = _user_allowed_compartments(user)
    if allowed is None:
        return True
    return compartment_id in allowed


def _check_action_allowed(user: User, action: str):
    if user.role == Role.admin:
        return
    if not user.allowed_actions:
        return   # empty → role defaults: operators can do all actions
    allowed = [a.strip().upper() for a in user.allowed_actions.split(",") if a.strip()]
    if allowed and action.upper() not in allowed:
        raise HTTPException(
            403, f"Action '{action}' not in your permitted list: {', '.join(allowed)}"
        )


# ── Audit writer ──────────────────────────────────────────────────

async def _write_audit(db, user: User, action: str, resource: str,
                        compartment: str = "", region: str = "", ip: str = ""):
    db.add(AuditLog(
        username=user.username,
        user_email=user.email,
        action=action,
        resource=resource,
        compartment=compartment,
        region=region,
        source_ip=ip,
    ))
    await db.commit()


# ── Endpoints ─────────────────────────────────────────────────────

@router.get("/regions")
async def list_regions(_: User = Depends(get_current_user)):
    return OCI_REGIONS


@router.get("/compartments", response_model=List[CompartmentOut])
async def list_compartments(
    region: str = Query(..., description="OCI region key, e.g. ap-sydney-1"),
    current_user: User = Depends(get_current_user),
):
    """
    List compartments the *current user* is allowed to see.
    - Admins see all active compartments in the tenancy.
    - Operators/Viewers see only their scoped compartments.
    The region param is required so the identity client
    uses the correct regional endpoint.
    """
    try:
        id_client  = get_identity_client(region)
        base_cfg   = get_base_config()
        tenancy_id = base_cfg.get("tenancy", "")

        response = oci.pagination.list_call_get_all_results(
            id_client.list_compartments,
            tenancy_id,
            compartment_id_in_subtree=True,
            lifecycle_state="ACTIVE",
        )
        all_comps = response.data

    except oci.exceptions.ServiceError as exc:
        app_logger.error(f"OCI list_compartments [{region}]: {exc}")
        raise HTTPException(502, f"OCI API error: {exc.message}")

    # Filter by user scope
    allowed = _user_allowed_compartments(current_user)
    result = []
    for c in all_comps:
        if allowed is None or c.id in allowed:
            result.append(CompartmentOut(
                id=c.id, name=c.name, description=c.description or ""
            ))

    app_logger.debug(
        f"list_compartments region={region} user={current_user.username} "
        f"→ {len(result)}/{len(all_comps)}"
    )
    return result


@router.get("/instances", response_model=List[InstanceOut])
async def list_instances(
    compartment_id:  str = Query(...),
    region:          str = Query(..., description="OCI region key — required for correct endpoint"),
    lifecycle_state: str = Query(None),
    current_user: User = Depends(get_current_user),
):
    """
    List compute instances.
    - region  → selects the correct OCI regional endpoint (fixes cross-region bleed)
    - compartment_id → must be in user's scope (enforced server-side)
    - tag_filters → instances not matching user's tag rules are hidden
    """
    # Enforce compartment scope
    if not _compartment_allowed(current_user, compartment_id):
        raise HTTPException(
            403, "You do not have access to this compartment"
        )

    try:
        # ← KEY FIX: create a region-specific compute client
        cmp_client = get_compute_client(region)

        kwargs: dict = {"compartment_id": compartment_id}
        if lifecycle_state:
            kwargs["lifecycle_state"] = lifecycle_state

        response = oci.pagination.list_call_get_all_results(
            cmp_client.list_instances, **kwargs
        )

    except oci.exceptions.ServiceError as exc:
        app_logger.error(f"OCI list_instances [{region}/{compartment_id}]: {exc}")
        raise HTTPException(502, f"OCI API error: {exc.message}")

    # Parse user's tag filters once
    tag_filters = _parse_tag_filters(current_user)
    if tag_filters:
        app_logger.debug(
            f"list_instances tag_filters for {current_user.username}: {tag_filters}"
        )

    instances = []
    for i in response.data:
        if i.lifecycle_state == "TERMINATED":
            continue
        # Tag filter enforcement
        if not _instance_matches_tags(i, tag_filters):
            app_logger.debug(
                f"Instance {i.display_name} excluded by tag filter "
                f"(freeform={i.freeform_tags}, defined={list((i.defined_tags or {}).keys())})"
            )
            continue

        ocpus = ram = None
        if i.shape_config:
            ocpus = int(i.shape_config.ocpus or 0)
            ram   = round(i.shape_config.memory_in_gbs or 0, 1)

        instances.append(InstanceOut(
            id=i.id,
            name=i.display_name,
            status=i.lifecycle_state,
            shape=i.shape,
            region=region,              # use the requested region, not i.region
            compartment_id=i.compartment_id,
            vcpus=ocpus,
            ram_gb=ram,
            freeform_tags=i.freeform_tags or {},
            defined_tags=i.defined_tags  or {},
        ))

    app_logger.debug(
        f"list_instances region={region} cmp={compartment_id} "
        f"user={current_user.username} → {len(instances)} instances"
    )
    return instances


@router.post("/instances/{instance_id}/action")
async def instance_action(
    instance_id: str,
    body:        ActionRequest,
    request:     Request,
    region:      str = Query(..., description="OCI region key"),
    current_user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    """
    Perform START / STOP / SOFTRESET on an instance.
    Enforces: compartment scope, allowed_actions, tag filters.
    """
    # Action permission check
    _check_action_allowed(current_user, body.action.value)

    cmp_client = get_compute_client(region)

    # Fetch instance to get compartment + tags
    try:
        inst_resp = cmp_client.get_instance(instance_id)
        instance  = inst_resp.data
    except oci.exceptions.ServiceError as exc:
        if exc.status == 404:
            raise HTTPException(404, "Instance not found")
        raise HTTPException(502, f"OCI API error: {exc.message}")

    # Compartment scope check
    if not _compartment_allowed(current_user, instance.compartment_id):
        raise HTTPException(403, "You do not have access to this compartment")

    # Tag filter check
    tag_filters = _parse_tag_filters(current_user)
    if not _instance_matches_tags(instance, tag_filters):
        raise HTTPException(403, "This instance does not match your tag access rules")

    # Execute action
    try:
        cmp_client.instance_action(instance_id, body.action.value)
        app_logger.info(
            f"instance_action {body.action} on {instance_id} "
            f"region={region} by {current_user.username}"
        )
    except oci.exceptions.ServiceError as exc:
        app_logger.error(f"OCI instance_action: {exc}")
        raise HTTPException(502, f"OCI API error: {exc.message}")

    await _write_audit(
        db, current_user,
        action=body.action.value,
        resource=instance.display_name,
        compartment=instance.compartment_id,
        region=region,
        ip=request.client.host,
    )
    audit_logger.info(
        f"user={current_user.username} action={body.action.value} "
        f"resource={instance.display_name} region={region} "
        f"ip={request.client.host}"
    )
    return {"ok": True, "instance_id": instance_id, "action": body.action}
