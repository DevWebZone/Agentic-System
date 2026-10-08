from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db_session
from app.orchestration.engine import WorkflowEngine
from app.orchestration.governance import add_clarification, approve, reject, revise_requirement
from app.orchestration.models import Approval, Workflow
from app.orchestration.observability import (
    orchestration_metrics,
    workflow_graph,
    workflow_summary,
    workflow_timeline,
)
from app.orchestration.scenarios import ScenarioRunner
from app.orchestration.schemas import (
    ApprovalDecisionRequest,
    ApprovalResponse,
    AuditEventResponse,
    ClarificationRequest,
    CreateWorkflowRequest,
    OrchestrationMetricsResponse,
    ReviseRequirementRequest,
    RunWorkflowResponse,
    ScenarioResponse,
    ScenarioRunResponse,
    WorkflowGraphResponse,
    WorkflowNodeResponse,
    WorkflowResponse,
    WorkflowSummaryResponse,
)

router = APIRouter(prefix="/api/v1/workflows", tags=["workflows"])
metrics_router = APIRouter(prefix="/api/v1/orchestration", tags=["orchestration"])
scenarios_router = APIRouter(prefix="/api/v1/scenarios", tags=["scenarios"])


def get_engine(session: Session = Depends(get_db_session)) -> WorkflowEngine:
    return WorkflowEngine(session)


def get_scenario_runner(session: Session = Depends(get_db_session)) -> ScenarioRunner:
    return ScenarioRunner(session)


def to_workflow_response(workflow: Workflow) -> WorkflowResponse:
    return WorkflowResponse(
        id=workflow.id,
        title=workflow.title,
        original_requirement=workflow.original_requirement,
        status=workflow.status,
        context_version=workflow.context_version,
        graph_version=workflow.graph_version,
        created_at=workflow.created_at,
        completed_at=workflow.completed_at,
        nodes=[
            WorkflowNodeResponse(
                id=node.id,
                node_key=node.node_key,
                node_type=node.node_type,
                assigned_agent=node.assigned_agent,
                status=node.status,
                dependency_keys=node.dependency_keys,
                concern_tags=node.concern_tags,
                input_context_version=node.input_context_version,
                output_artifact=node.output_artifact,
                error_message=node.error_message,
            )
            for node in sorted(workflow.nodes, key=lambda item: item.id)
        ],
    )


def to_approval_response(approval: Approval) -> ApprovalResponse:
    return ApprovalResponse(
        id=approval.id,
        workflow_id=approval.workflow_id,
        workflow_node_id=approval.workflow_node_id,
        status=approval.status,
        reviewer=approval.reviewer,
        comments=approval.comments,
        requested_at=approval.requested_at,
        resolved_at=approval.resolved_at,
    )


@router.post("", response_model=WorkflowResponse, status_code=201)
def create_workflow(
    payload: CreateWorkflowRequest, engine: WorkflowEngine = Depends(get_engine)
) -> WorkflowResponse:
    return to_workflow_response(engine.create_workflow(payload))


@router.get("/{workflow_id}", response_model=WorkflowResponse)
def get_workflow(
    workflow_id: int, engine: WorkflowEngine = Depends(get_engine)
) -> WorkflowResponse:
    return to_workflow_response(engine.get_workflow(workflow_id))


@router.get("/{workflow_id}/graph", response_model=WorkflowGraphResponse)
def get_workflow_graph(
    workflow_id: int, engine: WorkflowEngine = Depends(get_engine)
) -> WorkflowGraphResponse:
    return WorkflowGraphResponse.model_validate(workflow_graph(engine.get_workflow(workflow_id)))


@router.get("/{workflow_id}/timeline", response_model=list[AuditEventResponse])
def get_workflow_timeline(
    workflow_id: int,
    session: Session = Depends(get_db_session),
    engine: WorkflowEngine = Depends(get_engine),
) -> list[AuditEventResponse]:
    engine.get_workflow(workflow_id)
    return [
        AuditEventResponse.model_validate(event)
        for event in workflow_timeline(session, workflow_id)
    ]


@router.get("/{workflow_id}/audit", response_model=list[AuditEventResponse])
def get_workflow_audit(
    workflow_id: int,
    session: Session = Depends(get_db_session),
    engine: WorkflowEngine = Depends(get_engine),
) -> list[AuditEventResponse]:
    engine.get_workflow(workflow_id)
    return [
        AuditEventResponse.model_validate(event)
        for event in workflow_timeline(session, workflow_id)
    ]


@router.get("/{workflow_id}/summary", response_model=WorkflowSummaryResponse)
def get_workflow_summary(
    workflow_id: int,
    session: Session = Depends(get_db_session),
    engine: WorkflowEngine = Depends(get_engine),
) -> WorkflowSummaryResponse:
    return WorkflowSummaryResponse.model_validate(
        workflow_summary(session, engine.get_workflow(workflow_id))
    )


@router.post("/{workflow_id}/run", response_model=RunWorkflowResponse)
def run_workflow(
    workflow_id: int, engine: WorkflowEngine = Depends(get_engine)
) -> RunWorkflowResponse:
    workflow, waves_executed, executed_node_keys = engine.run(workflow_id)
    return RunWorkflowResponse(
        workflow=to_workflow_response(workflow),
        waves_executed=waves_executed,
        executed_node_keys=executed_node_keys,
    )


@router.post("/{workflow_id}/resume", response_model=RunWorkflowResponse)
def resume_workflow(
    workflow_id: int, engine: WorkflowEngine = Depends(get_engine)
) -> RunWorkflowResponse:
    workflow, waves_executed, executed_node_keys = engine.run(workflow_id, resume=True)
    return RunWorkflowResponse(
        workflow=to_workflow_response(workflow),
        waves_executed=waves_executed,
        executed_node_keys=executed_node_keys,
    )


@router.get("/{workflow_id}/approvals", response_model=list[ApprovalResponse])
def list_approvals(
    workflow_id: int,
    session: Session = Depends(get_db_session),
    engine: WorkflowEngine = Depends(get_engine),
) -> list[ApprovalResponse]:
    engine.get_workflow(workflow_id)
    approvals = (
        session.query(Approval).filter(Approval.workflow_id == workflow_id).order_by(Approval.id)
    )
    return [to_approval_response(approval) for approval in approvals]


@router.post("/{workflow_id}/approvals/{approval_id}/approve", response_model=ApprovalResponse)
def approve_workflow_action(
    workflow_id: int,
    approval_id: int,
    payload: ApprovalDecisionRequest,
    session: Session = Depends(get_db_session),
    engine: WorkflowEngine = Depends(get_engine),
) -> ApprovalResponse:
    workflow = engine.get_workflow(workflow_id)
    approval = session.get(Approval, approval_id)
    if approval is None or approval.workflow_id != workflow.id:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval was not found.")
    return to_approval_response(
        approve(session, workflow, approval, payload.reviewer, payload.comments)
    )


@router.post("/{workflow_id}/approvals/{approval_id}/reject", response_model=ApprovalResponse)
def reject_workflow_action(
    workflow_id: int,
    approval_id: int,
    payload: ApprovalDecisionRequest,
    session: Session = Depends(get_db_session),
    engine: WorkflowEngine = Depends(get_engine),
) -> ApprovalResponse:
    workflow = engine.get_workflow(workflow_id)
    approval = session.get(Approval, approval_id)
    if approval is None or approval.workflow_id != workflow.id:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval was not found.")
    return to_approval_response(
        reject(session, workflow, approval, payload.reviewer, payload.comments)
    )


@router.post("/{workflow_id}/clarifications", response_model=WorkflowResponse)
def clarify_workflow(
    workflow_id: int,
    payload: ClarificationRequest,
    session: Session = Depends(get_db_session),
    engine: WorkflowEngine = Depends(get_engine),
) -> WorkflowResponse:
    workflow = engine.get_workflow(workflow_id)
    return to_workflow_response(
        add_clarification(session, workflow, payload.response, payload.actor)
    )


@router.post("/{workflow_id}/requirements/revise", response_model=WorkflowResponse)
def revise_workflow_requirement(
    workflow_id: int,
    payload: ReviseRequirementRequest,
    session: Session = Depends(get_db_session),
    engine: WorkflowEngine = Depends(get_engine),
) -> WorkflowResponse:
    workflow = engine.get_workflow(workflow_id)
    revised = revise_requirement(
        session,
        workflow,
        requirement=payload.requirement,
        changed_concerns=payload.changed_concerns,
        actor=payload.actor,
        reason=payload.reason,
    )
    return to_workflow_response(revised)


@metrics_router.get("/metrics", response_model=OrchestrationMetricsResponse)
def get_orchestration_metrics(
    session: Session = Depends(get_db_session),
) -> OrchestrationMetricsResponse:
    return OrchestrationMetricsResponse.model_validate(orchestration_metrics(session))


@scenarios_router.get("", response_model=list[ScenarioResponse])
def list_scenarios(runner: ScenarioRunner = Depends(get_scenario_runner)) -> list[ScenarioResponse]:
    return [ScenarioResponse.model_validate(item) for item in runner.available()]


@scenarios_router.post("/{scenario_name}/run", response_model=ScenarioRunResponse)
def run_scenario(
    scenario_name: str, runner: ScenarioRunner = Depends(get_scenario_runner)
) -> ScenarioRunResponse:
    workflow = runner.run(scenario_name)
    return ScenarioRunResponse(scenario=scenario_name, workflow=to_workflow_response(workflow))
