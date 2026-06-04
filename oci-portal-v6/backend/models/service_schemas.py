"""
Pydantic schemas for service group, instance, and sequence management.
Used for request/response validation and serialization.
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


# ============================================
# Service Instance Schemas
# ============================================

class ServiceInstanceCreate(BaseModel):
    """Request to add an instance to a service group"""
    oci_instance_id: str = Field(..., min_length=1)
    instance_name: str = Field(..., min_length=1)
    region: str = Field(..., min_length=1)
    compartment_id: str = Field(..., min_length=1)


class ServiceInstanceResponse(BaseModel):
    """Response with service instance details"""
    id: int
    service_group_id: int
    oci_instance_id: str
    instance_name: str
    region: str
    compartment_id: str
    sequence_order: int
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================
# Service Sequence Schemas
# ============================================

class ServiceSequenceCreate(BaseModel):
    """Request to create a sequence step"""
    action: str = Field(..., pattern="^(start|stop)$")
    instance_id: int
    sequence_number: int = Field(..., ge=1)
    wait_minutes: int = Field(default=0, ge=0)
    condition_type: Optional[str] = Field(None, pattern="^(minutes_after|status_check|manual)?$")
    condition_value: Optional[str] = None


class ServiceSequenceUpdate(BaseModel):
    """Request to update a sequence step"""
    action: Optional[str] = Field(None, pattern="^(start|stop)$")
    instance_id: Optional[int] = None
    sequence_number: Optional[int] = Field(None, ge=1)
    wait_minutes: Optional[int] = Field(None, ge=0)
    condition_type: Optional[str] = Field(None, pattern="^(minutes_after|status_check|manual)?$")
    condition_value: Optional[str] = None


class ServiceSequenceResponse(BaseModel):
    """Response with sequence step details"""
    id: int
    service_group_id: int
    action: str
    instance_id: int
    sequence_number: int
    wait_minutes: int
    condition_type: Optional[str]
    condition_value: Optional[str]
    created_at: datetime
    created_by: int

    class Config:
        from_attributes = True


# ============================================
# Service Group Schemas
# ============================================

class ServiceGroupCreate(BaseModel):
    """Request to create a new service group"""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)


class ServiceGroupUpdate(BaseModel):
    """Request to update a service group"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    is_active: Optional[bool] = None


class ServiceGroupResponse(BaseModel):
    """Response with service group details"""
    id: int
    name: str
    description: Optional[str]
    created_by: int
    created_at: datetime
    is_active: bool

    class Config:
        from_attributes = True


class ServiceGroupDetailResponse(ServiceGroupResponse):
    """Extended response including instances and sequences"""
    instances: List[ServiceInstanceResponse] = []
    sequences: List[ServiceSequenceResponse] = []


# ============================================
# Service Execution Schemas
# ============================================

class ServiceExecutionStart(BaseModel):
    """Request to start/stop a service"""
    action: str = Field(..., pattern="^(start|stop)$")


class ServiceExecutionResponse(BaseModel):
    """Response with execution status"""
    id: int
    service_group_id: int
    action: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    status: str  # 'running', 'completed', 'failed', 'cancelled'
    executed_by: int
    error_message: Optional[str] = None

    class Config:
        from_attributes = True


class ServiceExecutionStatusResponse(BaseModel):
    """Real-time status of an ongoing execution"""
    execution_id: int
    service_group_id: int
    action: str
    status: str  # 'running', 'completed', 'failed', 'cancelled'
    current_step: Optional[int] = None
    total_steps: Optional[int] = None
    progress_percent: int
    last_instance_name: Optional[str] = None
    error_message: Optional[str] = None
    elapsed_seconds: int


class ServiceStatusResponse(BaseModel):
    """Overall status of a service group"""
    service_group_id: int
    service_name: str
    is_active: bool
    instance_count: int
    last_execution: Optional[ServiceExecutionResponse] = None
    overall_instance_status: Optional[str] = None  # e.g., "3 RUNNING, 2 STOPPED"
