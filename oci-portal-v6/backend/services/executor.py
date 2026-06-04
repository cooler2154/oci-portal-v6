"""
Service Executor Engine
Orchestrates sequential start/stop of instances with conditional delays and status checks.
Handles execution state, logging, and error recovery.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from core.logging_setup import app_logger
from core.oci_client import OCIClientFactory
from db.models import User
from db.service_models import ServiceGroup, ServiceInstance, ServiceSequence, ServiceExecution


class ExecutionStep:
    """Represents a single step in the execution sequence"""
    
    def __init__(self, step_id: int, instance: ServiceInstance, action: str, 
                 sequence_number: int, wait_minutes: int, condition_type: Optional[str],
                 condition_value: Optional[str]):
        self.step_id = step_id
        self.instance = instance
        self.action = action  # 'start' or 'stop'
        self.sequence_number = sequence_number
        self.wait_minutes = wait_minutes
        self.condition_type = condition_type
        self.condition_value = condition_value
        self.status = "pending"  # pending, waiting, executing, completed, failed
        self.error = None
        self.started_at = None
        self.completed_at = None


class ServiceExecutor:
    """
    Orchestrates sequential start/stop of instances with conditions and delays.
    
    Features:
    - Sequential execution based on configurable order
    - Conditional waits (time-based, status-based, manual)
    - Real-time status tracking
    - Comprehensive error handling and logging
    - Audit trail integration
    """
    
    def __init__(self, db: AsyncSession, oci_factory: OCIClientFactory):
        self.db = db
        self.oci_factory = oci_factory
        self.execution_state: Dict = {}  # Track execution progress
        self.execution_id: Optional[int] = None
        self.execution_steps: List[ExecutionStep] = []
        self.current_step_index = 0
        
    async def execute_service(
        self,
        service_group_id: int,
        action: str,  # 'start' or 'stop'
        user_id: int
    ) -> Dict:
        """
        Execute start/stop sequence for a service group.
        
        Args:
            service_group_id: ID of the service group to execute
            action: 'start' or 'stop'
            user_id: ID of the user triggering execution
            
        Returns:
            Dictionary with execution summary
        """
        try:
            app_logger.info(f"Starting {action} execution for service group {service_group_id}")
            
            # 1. Load service group and sequences
            service_group = await self._load_service_group(service_group_id)
            if not service_group:
                return {"success": False, "error": f"Service group {service_group_id} not found"}
            
            if not service_group.instances:
                return {"success": False, "error": "Service group has no instances"}
            
            # 2. Create execution record
            execution = ServiceExecution(
                service_group_id=service_group_id,
                action=action,
                started_at=datetime.utcnow(),
                status="running",
                executed_by=user_id
            )
            self.db.add(execution)
            await self.db.commit()
            self.execution_id = execution.id
            
            app_logger.info(f"Created execution record ID {self.execution_id}")
            
            # 3. Load and sort execution steps
            await self._load_execution_steps(service_group_id, action)
            
            if not self.execution_steps:
                return {"success": False, "error": "No sequence steps configured for this action"}
            
            # 4. Execute steps in sequence
            failed_steps = []
            for idx, step in enumerate(self.execution_steps):
                self.current_step_index = idx
                step.status = "executing"
                
                try:
                    # Check pre-execution condition
                    if not await self._check_condition(step, is_pre_condition=True):
                        app_logger.warning(f"Pre-condition failed for step {step.sequence_number}")
                        step.status = "failed"
                        step.error = "Pre-execution condition not met"
                        failed_steps.append(step)
                        continue
                    
                    # Wait if needed
                    if step.wait_minutes > 0:
                        app_logger.info(f"Waiting {step.wait_minutes} minutes before step {step.sequence_number}")
                        await asyncio.sleep(step.wait_minutes * 60)
                    
                    # Execute the action
                    await self._execute_instance_action(step)
                    step.status = "completed"
                    step.completed_at = datetime.utcnow()
                    
                except Exception as e:
                    step.status = "failed"
                    step.error = str(e)
                    failed_steps.append(step)
                    app_logger.error(f"Error executing step {step.sequence_number}: {e}")
                    
                    # If critical failure, stop execution
                    if not await self._should_continue_on_error(step):
                        break
            
            # 5. Update execution record
            await self._finalize_execution(failed_steps)
            
            # 6. Return summary
            summary = {
                "success": len(failed_steps) == 0,
                "execution_id": self.execution_id,
                "service_group_id": service_group_id,
                "action": action,
                "total_steps": len(self.execution_steps),
                "completed_steps": sum(1 for s in self.execution_steps if s.status == "completed"),
                "failed_steps": len(failed_steps),
                "errors": [{"step": s.sequence_number, "error": s.error} for s in failed_steps]
            }
            
            app_logger.info(f"Execution {self.execution_id} completed: {summary}")
            return summary
            
        except Exception as e:
            app_logger.error(f"Fatal error in execute_service: {e}")
            if self.execution_id:
                await self._mark_execution_failed(str(e))
            return {"success": False, "error": str(e)}
    
    
    async def _load_service_group(self, service_group_id: int) -> Optional[ServiceGroup]:
        """Load service group with all instances"""
        result = await self.db.execute(
            select(ServiceGroup).where(ServiceGroup.id == service_group_id)
        )
        return result.scalars().first()
    
    
    async def _load_execution_steps(self, service_group_id: int, action: str):
        """Load and sort execution steps by sequence number"""
        result = await self.db.execute(
            select(ServiceSequence)
            .where(
                (ServiceSequence.service_group_id == service_group_id) &
                (ServiceSequence.action == action)
            )
            .order_by(ServiceSequence.sequence_number)
        )
        
        sequences = result.scalars().all()
        self.execution_steps = [
            ExecutionStep(
                step_id=seq.id,
                instance=seq.instance,
                action=seq.action,
                sequence_number=seq.sequence_number,
                wait_minutes=seq.wait_minutes,
                condition_type=seq.condition_type,
                condition_value=seq.condition_value
            )
            for seq in sequences
        ]
    
    
    async def _check_condition(self, step: ExecutionStep, is_pre_condition: bool = False) -> bool:
        """
        Evaluate condition for a step.
        
        Condition types:
        - 'minutes_after': Already handled by wait_minutes
        - 'status_check': Wait for instance to reach target status
        - 'manual': Would require manual approval (not auto-executed)
        - None: No condition, proceed immediately
        """
        if not step.condition_type:
            return True
        
        if step.condition_type == "manual":
            app_logger.info(f"Step {step.sequence_number} requires manual approval")
            return False  # Manual steps not auto-approved
        
        if step.condition_type == "status_check":
            # Wait for instance to reach target status
            target_status = step.condition_value  # e.g., 'RUNNING', 'STOPPED'
            return await self._wait_for_instance_status(
                step.instance,
                target_status,
                timeout=300  # 5 minutes timeout
            )
        
        return True
    
    
    async def _execute_instance_action(self, step: ExecutionStep):
        """Execute start/stop action on an OCI instance"""
        step.started_at = datetime.utcnow()
        
        app_logger.info(f"Executing {step.action} on instance {step.instance.instance_name} "
                       f"({step.instance.oci_instance_id}) in {step.instance.region}")
        
        try:
            # Get OCI client for the region
            client = self.oci_factory.get_compute_client(step.instance.region)
            
            if step.action == "start":
                client.instance_action(
                    instance_id=step.instance.oci_instance_id,
                    action="START"
                )
                app_logger.info(f"Sent START signal to {step.instance.instance_name}")
                
            elif step.action == "stop":
                client.instance_action(
                    instance_id=step.instance.oci_instance_id,
                    action="STOP"
                )
                app_logger.info(f"Sent STOP signal to {step.instance.instance_name}")
            
            # Poll for confirmation
            await self._wait_for_instance_status(
                step.instance,
                "RUNNING" if step.action == "start" else "STOPPED",
                timeout=600  # 10 minutes
            )
            
        except Exception as e:
            app_logger.error(f"Failed to execute {step.action} on {step.instance.instance_name}: {e}")
            raise
    
    
    async def _wait_for_instance_status(
        self,
        instance: ServiceInstance,
        target_status: str,
        timeout: int = 300
    ) -> bool:
        """
        Poll instance status until target status is reached or timeout.
        
        Args:
            instance: ServiceInstance to check
            target_status: 'RUNNING' or 'STOPPED'
            timeout: Max seconds to wait (default 5 minutes)
            
        Returns:
            True if target status reached, False on timeout
        """
        start_time = datetime.utcnow()
        poll_interval = 10  # Check every 10 seconds
        
        app_logger.info(f"Waiting for {instance.instance_name} to reach {target_status} "
                       f"(timeout: {timeout}s)")
        
        try:
            client = self.oci_factory.get_compute_client(instance.region)
            
            while True:
                # Check elapsed time
                elapsed = (datetime.utcnow() - start_time).total_seconds()
                if elapsed > timeout:
                    app_logger.warning(f"Timeout waiting for {instance.instance_name} "
                                     f"to reach {target_status}")
                    return False
                
                # Get current status
                response = client.get_instance(instance.oci_instance_id)
                current_status = response.data.lifecycle_state
                
                app_logger.debug(f"{instance.instance_name} status: {current_status} "
                               f"(elapsed: {int(elapsed)}s)")
                
                if current_status == target_status:
                    app_logger.info(f"{instance.instance_name} reached {target_status}")
                    return True
                
                # Wait before next poll
                await asyncio.sleep(poll_interval)
                
        except Exception as e:
            app_logger.error(f"Error checking status of {instance.instance_name}: {e}")
            return False
    
    
    async def _should_continue_on_error(self, failed_step: ExecutionStep) -> bool:
        """
        Determine if execution should continue after a step failure.
        Currently continues on error unless it's a critical failure.
        Can be extended with retry logic or rollback.
        """
        # TODO: Add configuration for fail-fast vs. continue-on-error behavior
        return True
    
    
    async def _finalize_execution(self, failed_steps: List[ExecutionStep]):
        """Update execution record with final status"""
        status = "failed" if failed_steps else "completed"
        error_msg = None
        
        if failed_steps:
            errors = [f"Step {s.sequence_number}: {s.error}" for s in failed_steps]
            error_msg = "; ".join(errors)
        
        stmt = (
            update(ServiceExecution)
            .where(ServiceExecution.id == self.execution_id)
            .values(
                status=status,
                completed_at=datetime.utcnow(),
                error_message=error_msg
            )
        )
        
        await self.db.execute(stmt)
        await self.db.commit()
    
    
    async def _mark_execution_failed(self, error_msg: str):
        """Mark execution as failed with error message"""
        stmt = (
            update(ServiceExecution)
            .where(ServiceExecution.id == self.execution_id)
            .values(
                status="failed",
                completed_at=datetime.utcnow(),
                error_message=error_msg
            )
        )
        
        await self.db.execute(stmt)
        await self.db.commit()
    
    
    async def get_execution_status(self, execution_id: int) -> Dict:
        """Get real-time status of an ongoing execution"""
        result = await self.db.execute(
            select(ServiceExecution).where(ServiceExecution.id == execution_id)
        )
        execution = result.scalars().first()
        
        if not execution:
            return {"error": "Execution not found"}
        
        elapsed = (datetime.utcnow() - execution.started_at).total_seconds()
        current_step = self.current_step_index + 1 if self.execution_steps else 0
        total_steps = len(self.execution_steps)
        progress = int((current_step / total_steps * 100)) if total_steps > 0 else 0
        
        current_instance_name = None
        if 0 <= self.current_step_index < len(self.execution_steps):
            current_instance_name = self.execution_steps[self.current_step_index].instance.instance_name
        
        return {
            "execution_id": execution_id,
            "service_group_id": execution.service_group_id,
            "action": execution.action,
            "status": execution.status,
            "current_step": current_step,
            "total_steps": total_steps,
            "progress_percent": progress,
            "last_instance_name": current_instance_name,
            "error_message": execution.error_message,
            "elapsed_seconds": int(elapsed)
        }
