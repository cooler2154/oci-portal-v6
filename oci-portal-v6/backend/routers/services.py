"""
FastAPI router for Services feature.
Handles service group CRUD, instance management, sequence configuration, and execution.
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging_setup import app_logger
from core.oci_client import OCIClientFactory
from db.database import get_db
from db.models import User
from db.service_models import ServiceGroup, ServiceInstance, ServiceSequence, ServiceExecution
from routers.auth import get_current_user, require_admin, require_operator_or_admin
from models.service_schemas import (
    ServiceGroupCreate, ServiceGroupUpdate, ServiceGroupResponse, ServiceGroupDetailResponse,
    ServiceInstanceCreate, ServiceInstanceResponse,
    ServiceSequenceCreate, ServiceSequenceUpdate, ServiceSequenceResponse,
    ServiceExecutionStart, ServiceExecutionResponse, ServiceExecutionStatusResponse
)
from services.executor import ServiceExecutor


router = APIRouter(prefix="/api/services", tags=["services"])


# ============================================================================
# SERVICE GROUP ENDPOINTS
# ============================================================================

@router.get("/groups", response_model=List[ServiceGroupResponse])
async def list_service_groups(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_operator_or_admin)
):
    """List all active service groups (Operator/Admin only)"""
    result = await db.execute(
        select(ServiceGroup)
        .where(ServiceGroup.is_active == True)
        .order_by(ServiceGroup.name)
    )
    groups = result.scalars().all()
    return groups


@router.get("/groups/{group_id}", response_model=ServiceGroupDetailResponse)
async def get_service_group_details(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_operator_or_admin)
):
    """Get service group with all instances and sequences"""
    result = await db.execute(
        select(ServiceGroup).where(ServiceGroup.id == group_id)
    )
    group = result.scalars().first()
    
    if not group:
        raise HTTPException(status_code=404, detail="Service group not found")
    
    return group


@router.post("/groups", response_model=ServiceGroupResponse, status_code=201)
async def create_service_group(
    data: ServiceGroupCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Create a new service group (Admin only)"""
    
    # Check if name already exists
    result = await db.execute(
        select(ServiceGroup).where(ServiceGroup.name == data.name)
    )
    if result.scalars().first():
        raise HTTPException(
            status_code=400,
            detail=f"Service group '{data.name}' already exists"
        )
    
    group = ServiceGroup(
        name=data.name,
        description=data.description,
        created_by=current_user.id,
        is_active=True
    )
    
    db.add(group)
    await db.commit()
    await db.refresh(group)
    
    app_logger.info(f"Created service group '{group.name}' by user {current_user.username}")
    
    return group


@router.patch("/groups/{group_id}", response_model=ServiceGroupResponse)
async def update_service_group(
    group_id: int,
    data: ServiceGroupUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Update a service group (Admin only)"""
    
    result = await db.execute(
        select(ServiceGroup).where(ServiceGroup.id == group_id)
    )
    group = result.scalars().first()
    
    if not group:
        raise HTTPException(status_code=404, detail="Service group not found")
    
    # Check if renaming to an existing name
    if data.name and data.name != group.name:
        result = await db.execute(
            select(ServiceGroup).where(ServiceGroup.name == data.name)
        )
        if result.scalars().first():
            raise HTTPException(
                status_code=400,
                detail=f"Service group '{data.name}' already exists"
            )
    
    update_data = data.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(group, field, value)
    
    await db.commit()
    await db.refresh(group)
    
    app_logger.info(f"Updated service group {group_id} by user {current_user.username}")
    
    return group


@router.delete("/groups/{group_id}", status_code=204)
async def delete_service_group(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Delete a service group and all its instances/sequences (Admin only)"""
    
    result = await db.execute(
        select(ServiceGroup).where(ServiceGroup.id == group_id)
    )
    group = result.scalars().first()
    
    if not group:
        raise HTTPException(status_code=404, detail="Service group not found")
    
    await db.delete(group)
    await db.commit()
    
    app_logger.info(f"Deleted service group {group_id} by user {current_user.username}")


# ============================================================================
# SERVICE INSTANCE ENDPOINTS
# ============================================================================

@router.post("/groups/{group_id}/instances", response_model=ServiceInstanceResponse, status_code=201)
async def add_instance_to_group(
    group_id: int,
    data: ServiceInstanceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Add an OCI instance to a service group (Admin only)"""
    
    # Verify group exists
    result = await db.execute(
        select(ServiceGroup).where(ServiceGroup.id == group_id)
    )
    group = result.scalars().first()
    
    if not group:
        raise HTTPException(status_code=404, detail="Service group not found")
    
    instance = ServiceInstance(
        service_group_id=group_id,
        oci_instance_id=data.oci_instance_id,
        instance_name=data.instance_name,
        region=data.region,
        compartment_id=data.compartment_id,
        sequence_order=0
    )
    
    db.add(instance)
    await db.commit()
    await db.refresh(instance)
    
    app_logger.info(f"Added instance {data.instance_name} to group {group_id}")
    
    return instance


@router.delete("/instances/{instance_id}", status_code=204)
async def remove_instance_from_group(
    instance_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Remove an instance from a service group (Admin only)"""
    
    result = await db.execute(
        select(ServiceInstance).where(ServiceInstance.id == instance_id)
    )
    instance = result.scalars().first()
    
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    
    group_id = instance.service_group_id
    await db.delete(instance)
    await db.commit()
    
    app_logger.info(f"Removed instance {instance_id} from service group {group_id}")


# ============================================================================
# SEQUENCE ENDPOINTS
# ============================================================================

@router.get("/groups/{group_id}/sequences", response_model=List[ServiceSequenceResponse])
async def get_service_sequences(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_operator_or_admin)
):
    """Get all sequence steps for a service group"""
    
    result = await db.execute(
        select(ServiceGroup).where(ServiceGroup.id == group_id)
    )
    if not result.scalars().first():
        raise HTTPException(status_code=404, detail="Service group not found")
    
    result = await db.execute(
        select(ServiceSequence)
        .where(ServiceSequence.service_group_id == group_id)
        .order_by(ServiceSequence.action, ServiceSequence.sequence_number)
    )
    
    return result.scalars().all()


@router.post("/groups/{group_id}/sequences", response_model=ServiceSequenceResponse, status_code=201)
async def create_sequence_step(
    group_id: int,
    data: ServiceSequenceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Create a new sequence step for a service group (Admin only)"""
    
    # Verify group exists
    result = await db.execute(
        select(ServiceGroup).where(ServiceGroup.id == group_id)
    )
    if not result.scalars().first():
        raise HTTPException(status_code=404, detail="Service group not found")
    
    # Verify instance exists and belongs to this group
    result = await db.execute(
        select(ServiceInstance).where(
            (ServiceInstance.id == data.instance_id) &
            (ServiceInstance.service_group_id == group_id)
        )
    )
    if not result.scalars().first():
        raise HTTPException(status_code=404, detail="Instance not found in this group")
    
    sequence = ServiceSequence(
        service_group_id=group_id,
        action=data.action,
        instance_id=data.instance_id,
        sequence_number=data.sequence_number,
        wait_minutes=data.wait_minutes,
        condition_type=data.condition_type,
        condition_value=data.condition_value,
        created_by=current_user.id
    )
    
    db.add(sequence)
    await db.commit()
    await db.refresh(sequence)
    
    app_logger.info(f"Created sequence step for group {group_id}: {data.action} step {data.sequence_number}")
    
    return sequence


@router.patch("/sequences/{sequence_id}", response_model=ServiceSequenceResponse)
async def update_sequence_step(
    sequence_id: int,
    data: ServiceSequenceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Update a sequence step (Admin only)"""
    
    result = await db.execute(
        select(ServiceSequence).where(ServiceSequence.id == sequence_id)
    )
    sequence = result.scalars().first()
    
    if not sequence:
        raise HTTPException(status_code=404, detail="Sequence step not found")
    
    update_data = data.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(sequence, field, value)
    
    await db.commit()
    await db.refresh(sequence)
    
    app_logger.info(f"Updated sequence step {sequence_id}")
    
    return sequence


@router.delete("/sequences/{sequence_id}", status_code=204)
async def delete_sequence_step(
    sequence_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Delete a sequence step (Admin only)"""
    
    result = await db.execute(
        select(ServiceSequence).where(ServiceSequence.id == sequence_id)
    )
    sequence = result.scalars().first()
    
    if not sequence:
        raise HTTPException(status_code=404, detail="Sequence step not found")
    
    await db.delete(sequence)
    await db.commit()
    
    app_logger.info(f"Deleted sequence step {sequence_id}")


# ============================================================================
# EXECUTION ENDPOINTS
# ============================================================================

@router.post("/groups/{group_id}/execute", response_model=ServiceExecutionResponse, status_code=202)
async def execute_service(
    group_id: int,
    data: ServiceExecutionStart,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_operator_or_admin),
    oci_factory: OCIClientFactory = Depends(lambda: OCIClientFactory())
):
    """
    Start/stop a service group in configured sequence.
    - Viewers: can only execute 'start' action
    - Operators/Admins: can execute 'start' and 'stop'
    """
    
    # Viewer role check: only allow 'start' action
    if current_user.role == "viewer" and data.action != "start":
        raise HTTPException(
            status_code=403,
            detail="Viewers can only start services, not stop"
        )
    
    # Verify group exists
    result = await db.execute(
        select(ServiceGroup).where(ServiceGroup.id == group_id)
    )
    group = result.scalars().first()
    
    if not group:
        raise HTTPException(status_code=404, detail="Service group not found")
    
    # Execute service
    executor = ServiceExecutor(db, oci_factory)
    execution_summary = await executor.execute_service(
        service_group_id=group_id,
        action=data.action,
        user_id=current_user.id
    )
    
    if not execution_summary.get("success"):
        raise HTTPException(
            status_code=500,
            detail=execution_summary.get("error", "Execution failed")
        )
    
    # Return execution record
    result = await db.execute(
        select(ServiceExecution).where(ServiceExecution.id == execution_summary["execution_id"])
    )
    execution = result.scalars().first()
    
    return execution


@router.get("/executions/{execution_id}", response_model=ServiceExecutionStatusResponse)
async def get_execution_status(
    execution_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_operator_or_admin)
):
    """Get real-time status of a service execution"""
    
    result = await db.execute(
        select(ServiceExecution).where(ServiceExecution.id == execution_id)
    )
    execution = result.scalars().first()
    
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    
    # Calculate status details
    from datetime import datetime
    
    # Get sequence steps for progress calculation
    result = await db.execute(
        select(ServiceSequence).where(
            (ServiceSequence.service_group_id == execution.service_group_id) &
            (ServiceSequence.action == execution.action)
        )
    )
    steps = result.scalars().all()
    
    total_steps = len(steps)
    elapsed = (datetime.utcnow() - execution.started_at).total_seconds()
    
    # Estimate progress based on status
    progress_map = {
        "running": 50,
        "completed": 100,
        "failed": 0,
        "cancelled": 0
    }
    
    return ServiceExecutionStatusResponse(
        execution_id=execution_id,
        service_group_id=execution.service_group_id,
        action=execution.action,
        status=execution.status,
        current_step=None,  # Would need real-time tracking from executor
        total_steps=total_steps,
        progress_percent=progress_map.get(execution.status, 0),
        last_instance_name=None,
        error_message=execution.error_message,
        elapsed_seconds=int(elapsed)
    )


@router.get("/executions", response_model=List[ServiceExecutionResponse])
async def list_executions(
    group_id: int = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_operator_or_admin)
):
    """List recent service executions"""
    
    query = select(ServiceExecution)
    
    if group_id:
        query = query.where(ServiceExecution.service_group_id == group_id)
    
    # Operators only see their own executions
    if current_user.role == "operator":
        query = query.where(ServiceExecution.executed_by == current_user.id)
    
    result = await db.execute(
        query.order_by(ServiceExecution.started_at.desc()).limit(limit)
    )
    
    return result.scalars().all()
