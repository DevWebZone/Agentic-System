import pytest

from app.orchestration.graph import GraphNode, GraphValidationError, ready_nodes, validate_graph


def test_graph_cycle_is_rejected() -> None:
    nodes = [
        GraphNode(key="requirements", dependencies=("validation",)),
        GraphNode(key="validation", dependencies=("requirements",)),
    ]

    with pytest.raises(GraphValidationError, match="cycle"):
        validate_graph(nodes)


def test_parallel_nodes_become_ready_after_shared_dependency_succeeds() -> None:
    nodes = [
        GraphNode(key="requirements", status="SUCCEEDED"),
        GraphNode(key="architecture", dependencies=("requirements",)),
        GraphNode(key="risk_review", dependencies=("requirements",)),
        GraphNode(key="implementation", dependencies=("architecture", "risk_review")),
    ]

    assert {node.key for node in ready_nodes(nodes)} == {"architecture", "risk_review"}


def test_missing_dependency_is_rejected() -> None:
    with pytest.raises(GraphValidationError, match="missing dependencies"):
        validate_graph([GraphNode(key="requirements", dependencies=("missing",))])
