from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.orchestration.engine import WorkflowEngine
from app.orchestration.governance import (
    add_clarification,
    approve,
    reconcile_requirement_concerns,
    reject,
    revise_requirement,
)
from app.orchestration.models import (
    Approval,
    AuditEvent,
    ExecutionAttempt,
    NodeStatus,
    Workflow,
    WorkflowNode,
    WorkflowStatus,
)
from app.orchestration.schemas import CreateWorkflowRequest


def clear_workflows() -> None:
    with SessionLocal() as session:
        session.execute(delete(AuditEvent))
        session.execute(delete(Approval))
        session.execute(delete(ExecutionAttempt))
        session.execute(delete(WorkflowNode))
        session.execute(delete(Workflow))
        session.commit()


def test_high_risk_node_pauses_then_approval_resumes_execution() -> None:
    clear_workflows()
    with SessionLocal() as session:
        engine = WorkflowEngine(session)
        workflow = engine.create_workflow(
            CreateWorkflowRequest(
                title="Approval test",
                requirement="Change public link API.",
                nodes=[
                    {
                        "node_key": "implementation",
                        "node_type": "implementation",
                        "concern_tags": ["api"],
                    }
                ],
            )
        )
        waiting, _, _ = engine.run(workflow.id)
        approval = session.scalar(select(Approval).where(Approval.workflow_id == workflow.id))

        assert waiting.status == WorkflowStatus.WAITING_FOR_APPROVAL.value
        assert waiting.nodes[0].status == NodeStatus.WAITING_FOR_APPROVAL.value
        assert approval is not None and approval.status == "PENDING"

        approve(session, waiting, approval, "human-reviewer", "API reviewed")
        completed, _, _ = engine.run(workflow.id)

        assert completed.status == WorkflowStatus.COMPLETED.value
        assert completed.nodes[0].status == NodeStatus.SUCCEEDED.value


def test_rejected_approval_blocks_workflow() -> None:
    clear_workflows()
    with SessionLocal() as session:
        engine = WorkflowEngine(session)
        workflow = engine.create_workflow(
            CreateWorkflowRequest(
                title="Reject test",
                requirement="Migrate link schema.",
                nodes=[
                    {
                        "node_key": "implementation",
                        "node_type": "implementation",
                        "concern_tags": ["database"],
                    }
                ],
            )
        )
        waiting, _, _ = engine.run(workflow.id)
        approval = session.scalar(select(Approval).where(Approval.workflow_id == workflow.id))
        assert approval is not None

        rejected = reject(session, waiting, approval, "human-reviewer", "Migration not approved")

        assert rejected.status == "REJECTED"
        assert waiting.status == WorkflowStatus.FAILED.value
        assert waiting.nodes[0].status == NodeStatus.BLOCKED.value


def test_ambiguous_requirement_waits_for_input_and_clarification_resumes() -> None:
    clear_workflows()
    with SessionLocal() as session:
        engine = WorkflowEngine(session)
        workflow = engine.create_workflow(
            CreateWorkflowRequest(
                title="Ambiguous test",
                requirement="Make the URL shortener enterprise-ready.",
                nodes=[{"node_key": "requirements", "node_type": "requirements"}],
            )
        )
        waiting, _, _ = engine.run(workflow.id)

        assert waiting.status == WorkflowStatus.WAITING_FOR_INPUT.value
        assert waiting.nodes[0].status == NodeStatus.WAITING_FOR_INPUT.value

        add_clarification(session, waiting, "Require authenticated link management.", "reviewer")
        resumed, _, _ = engine.run(workflow.id)

        assert resumed.status == WorkflowStatus.COMPLETED.value
        assert "Require authenticated" in resumed.context["clarifications"][0]


def test_concern_replan_invalidates_only_affected_nodes_and_descendants() -> None:
    clear_workflows()
    with SessionLocal() as session:
        engine = WorkflowEngine(session)
        workflow = engine.create_workflow(
            CreateWorkflowRequest(
                title="Replan test",
                requirement="Improve analytics reporting.",
                nodes=[
                    {"node_key": "requirements", "node_type": "requirements"},
                    {
                        "node_key": "analytics",
                        "node_type": "architecture",
                        "dependency_keys": ["requirements"],
                        "concern_tags": ["analytics"],
                    },
                    {
                        "node_key": "api-change",
                        "node_type": "implementation",
                        "dependency_keys": ["requirements"],
                        "concern_tags": ["api", "security"],
                    },
                    {
                        "node_key": "api-tests",
                        "node_type": "testing",
                        "dependency_keys": ["api-change"],
                        "concern_tags": ["testing"],
                    },
                ],
            )
        )
        completed, _, _ = engine.run(workflow.id)
        assert completed.status == WorkflowStatus.WAITING_FOR_APPROVAL.value

        approval = session.scalar(select(Approval).where(Approval.workflow_id == workflow.id))
        assert approval is not None
        approve(session, completed, approval, "human-reviewer", "Initial API change approved")
        completed, _, _ = engine.run(workflow.id)
        assert completed.status == WorkflowStatus.COMPLETED.value

        replanned = revise_requirement(
            session,
            completed,
            requirement="Require authenticated API changes and secure analytics access.",
            changed_concerns=["api", "security"],
            actor="reviewer",
            reason="Security decision changed upstream requirement.",
        )
        nodes = {node.node_key: node for node in replanned.nodes}

        assert replanned.requirement_version == 2
        assert replanned.graph_version == 2
        assert nodes["requirements"].status == NodeStatus.PENDING.value
        assert nodes["api-change"].status == NodeStatus.PENDING.value
        assert nodes["api-tests"].status == NodeStatus.PENDING.value
        assert nodes["analytics"].status == NodeStatus.SUCCEEDED.value
        assert {artifact["node_key"] for artifact in replanned.artifacts} == {"analytics"}

        invalidated_approval = session.scalar(
            select(Approval).where(
                Approval.workflow_id == replanned.id,
                Approval.workflow_node_id == nodes["api-change"].id,
            )
        )
        assert invalidated_approval is not None
        assert invalidated_approval.status == "INVALIDATED"

        waiting, _, _ = engine.run(replanned.id)
        assert waiting.status == WorkflowStatus.WAITING_FOR_INPUT.value

        add_clarification(
            session,
            waiting,
            "Authenticated users may manage links; analytics require role-based access.",
            "reviewer",
        )
        waiting, _, _ = engine.run(replanned.id)
        assert waiting.status == WorkflowStatus.WAITING_FOR_APPROVAL.value


def test_changed_normalized_concerns_invalidate_planner_dependents() -> None:
    clear_workflows()
    with SessionLocal() as session:
        engine = WorkflowEngine(session)
        workflow = engine.create_workflow(
            CreateWorkflowRequest(
                title="Concern change replan test",
                requirement="Add a redirect API endpoint, tests, and documentation.",
            )
        )
        for node in workflow.nodes:
            node.status = NodeStatus.SUCCEEDED.value
        session.commit()

        replanned = revise_requirement(
            session,
            workflow,
            requirement="Refresh the developer guide only.",
            changed_concerns=["docs"],
            actor="reviewer",
            reason="Check the normalized concern set before invalidating the plan.",
        )
        replanned.normalized_requirement = "Refresh the developer guide only."
        session.commit()

        reconcile_requirement_concerns(session, replanned)
        nodes = {node.node_key: node for node in replanned.nodes}

        assert nodes["requirements"].status == NodeStatus.PENDING.value
        assert nodes["implementation"].status == NodeStatus.PENDING.value
        assert nodes["test-plan"].status == NodeStatus.PENDING.value
