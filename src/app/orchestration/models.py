from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class WorkflowStatus(StrEnum):
    DRAFT = "DRAFT"
    RUNNING = "RUNNING"
    WAITING_FOR_INPUT = "WAITING_FOR_INPUT"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SAFE_STOPPED = "SAFE_STOPPED"


class NodeStatus(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING_FOR_INPUT = "WAITING_FOR_INPUT"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    INVALIDATED = "INVALIDATED"
    ROLLED_BACK = "ROLLED_BACK"
    SAFE_STOPPED = "SAFE_STOPPED"
    CANCELLED = "CANCELLED"


class Workflow(Base):
    """Persisted workflow state and JSON-backed lineage retained for review and recovery."""

    __tablename__ = "workflows"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    original_requirement: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_requirement: Mapped[str | None] = mapped_column(Text, nullable=True)
    scenario_type: Mapped[str] = mapped_column(String(32), nullable=False, default="custom")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=WorkflowStatus.DRAFT.value
    )
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="MEDIUM")
    requirement_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    graph_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    context_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    artifacts: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    decisions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    checkpoints: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    safe_stop_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    nodes: Mapped[list["WorkflowNode"]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan", passive_deletes=True
    )


class WorkflowNode(Base):
    """A dependency-graph node executed only under workflow-engine governance."""

    __tablename__ = "workflow_nodes"
    __table_args__ = (Index("ix_workflow_nodes_workflow_id_status", "workflow_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"))
    node_key: Mapped[str] = mapped_column(String(100), nullable=False)
    node_type: Mapped[str] = mapped_column(String(64), nullable=False)
    assigned_agent: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=NodeStatus.PENDING.value
    )
    dependency_keys: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    concern_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    entry_criteria: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    exit_criteria: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    requires_approval: Mapped[bool] = mapped_column(nullable=False, default=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="MEDIUM")
    input_context_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    output_artifact: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    workflow: Mapped[Workflow] = relationship(back_populates="nodes")


class ExecutionAttempt(Base):
    """An auditable attempt to execute a workflow node."""

    __tablename__ = "execution_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_node_id: Mapped[int] = mapped_column(
        ForeignKey("workflow_nodes.id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    fallback_used: Mapped[bool] = mapped_column(nullable=False, default=False)
    error_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Approval(Base):
    """A durable human decision required to advance high-impact workflow work."""

    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"))
    workflow_node_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflow_nodes.id", ondelete="CASCADE"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    reviewer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    """Append-only review trail for state changes, policy decisions, and recovery actions."""

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_workflow_id_created_at", "workflow_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"))
    workflow_node_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflow_nodes.id", ondelete="SET NULL"), nullable=True
    )
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
