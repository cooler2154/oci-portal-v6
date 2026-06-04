"""
Service-related ORM models for managing business function groups and their instances.
Includes ServiceGroup, ServiceInstance, ServiceSequence, and ServiceExecution tables.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from db.database import Base


class ServiceGroup(Base):
    """
    Represents a business function group (e.g., JDE, Greentree, SAP).
    Groups multiple OCI instances that are logically related and can be
    started/stopped together in a controlled sequence.
    """
    __tablename__ = "service_groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(String(500), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    # Relationships
    instances = relationship("ServiceInstance", back_populates="service_group", cascade="all, delete-orphan")
    sequences = relationship("ServiceSequence", back_populates="service_group", cascade="all, delete-orphan")
    executions = relationship("ServiceExecution", back_populates="service_group", cascade="all, delete-orphan")


class ServiceInstance(Base):
    """
    Represents an OCI instance that belongs to a ServiceGroup.
    Stores reference to the actual OCI instance and its metadata.
    """
    __tablename__ = "service_instances"

    id = Column(Integer, primary_key=True, index=True)
    service_group_id = Column(Integer, ForeignKey("service_groups.id", ondelete="CASCADE"), nullable=False)
    oci_instance_id = Column(String(255), nullable=False, index=True)
    instance_name = Column(String(255), nullable=False)
    region = Column(String(50), nullable=False)
    compartment_id = Column(String(255), nullable=False)
    sequence_order = Column(Integer, default=0)  # Default order if not in custom sequence
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    service_group = relationship("ServiceGroup", back_populates="instances")
    sequences = relationship("ServiceSequence", back_populates="instance", cascade="all, delete-orphan")


class ServiceSequence(Base):
    """
    Defines the execution sequence for starting/stopping instances in a ServiceGroup.
    Includes wait times, conditions, and dependencies between instances.
    
    Condition types:
    - 'minutes_after': Wait X minutes after previous instance action
    - 'status_check': Wait for instance to reach specific status (RUNNING/STOPPED)
    - 'manual': Require manual confirmation before proceeding
    """
    __tablename__ = "service_sequences"

    id = Column(Integer, primary_key=True, index=True)
    service_group_id = Column(Integer, ForeignKey("service_groups.id", ondelete="CASCADE"), nullable=False)
    action = Column(String(10), nullable=False)  # 'start' or 'stop'
    instance_id = Column(Integer, ForeignKey("service_instances.id", ondelete="CASCADE"), nullable=False)
    sequence_number = Column(Integer, nullable=False)  # Execution order (1, 2, 3, ...)
    wait_minutes = Column(Integer, default=0)  # Minutes to wait before executing this step
    condition_type = Column(String(50), nullable=True)  # 'minutes_after', 'status_check', 'manual'
    condition_value = Column(String(255), nullable=True)  # e.g., '5' for 5 minutes, 'RUNNING' for status
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Relationships
    service_group = relationship("ServiceGroup", back_populates="sequences")
    instance = relationship("ServiceInstance", back_populates="sequences")


class ServiceExecution(Base):
    """
    Records the execution history of a service group start/stop action.
    Tracks when executions happen, their status, and any errors.
    """
    __tablename__ = "service_executions"

    id = Column(Integer, primary_key=True, index=True)
    service_group_id = Column(Integer, ForeignKey("service_groups.id", ondelete="CASCADE"), nullable=False)
    action = Column(String(10), nullable=False)  # 'start' or 'stop'
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    status = Column(String(20), default="running")  # 'running', 'completed', 'failed', 'cancelled'
    executed_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    error_message = Column(Text, nullable=True)

    # Relationships
    service_group = relationship("ServiceGroup", back_populates="executions")
