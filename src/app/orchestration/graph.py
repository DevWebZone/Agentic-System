from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass


class GraphValidationError(ValueError):
    """Raised when a workflow dependency graph cannot be safely executed."""


@dataclass(frozen=True)
class GraphNode:
    """Minimal graph representation independent from persistence and execution concerns."""

    key: str
    dependencies: tuple[str, ...] = ()
    status: str = "PENDING"


def validate_graph(nodes: Iterable[GraphNode]) -> None:
    """Reject duplicate keys, missing dependencies, cycles, and graphs without entry/exit nodes."""

    graph_nodes = list(nodes)
    if not graph_nodes:
        raise GraphValidationError("A workflow graph must contain at least one node.")

    keys = [node.key for node in graph_nodes]
    if len(keys) != len(set(keys)):
        raise GraphValidationError("Workflow node keys must be unique.")

    key_set = set(keys)
    for node in graph_nodes:
        missing = set(node.dependencies) - key_set
        if missing:
            missing_values = ", ".join(sorted(missing))
            raise GraphValidationError(
                f"Node '{node.key}' references missing dependencies: {missing_values}."
            )

    _assert_acyclic(graph_nodes)
    if not entry_nodes(graph_nodes):
        raise GraphValidationError("A workflow graph must contain an entry node.")
    if not exit_nodes(graph_nodes):
        raise GraphValidationError("A workflow graph must contain an exit node.")


def entry_nodes(nodes: Iterable[GraphNode]) -> list[GraphNode]:
    """Return nodes with no dependencies."""

    return [node for node in nodes if not node.dependencies]


def exit_nodes(nodes: Iterable[GraphNode]) -> list[GraphNode]:
    """Return nodes no other node depends on."""

    graph_nodes = list(nodes)
    dependency_keys = {dependency for node in graph_nodes for dependency in node.dependencies}
    return [node for node in graph_nodes if node.key not in dependency_keys]


def ready_nodes(nodes: Iterable[GraphNode]) -> list[GraphNode]:
    """Return all pending nodes whose dependencies have completed successfully."""

    graph_nodes = list(nodes)
    statuses = {node.key: node.status for node in graph_nodes}
    return [
        node
        for node in graph_nodes
        if node.status == "PENDING"
        and all(statuses[dependency] == "SUCCEEDED" for dependency in node.dependencies)
    ]


def downstream_nodes(nodes: Iterable[GraphNode], source_keys: set[str]) -> set[str]:
    """Return every transitive dependent for selective invalidation and future replanning."""

    graph_nodes = list(nodes)
    dependents: dict[str, set[str]] = {node.key: set() for node in graph_nodes}
    for node in graph_nodes:
        for dependency in node.dependencies:
            dependents[dependency].add(node.key)

    discovered: set[str] = set()
    queue = deque(source_keys)
    while queue:
        current = queue.popleft()
        for dependent in dependents.get(current, set()):
            if dependent not in discovered:
                discovered.add(dependent)
                queue.append(dependent)
    return discovered


def _assert_acyclic(nodes: list[GraphNode]) -> None:
    in_degree = {node.key: len(node.dependencies) for node in nodes}
    dependents: dict[str, list[str]] = {node.key: [] for node in nodes}
    for node in nodes:
        for dependency in node.dependencies:
            dependents[dependency].append(node.key)

    queue = deque(key for key, degree in in_degree.items() if degree == 0)
    visited_count = 0
    while queue:
        key = queue.popleft()
        visited_count += 1
        for dependent in dependents[key]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if visited_count != len(nodes):
        raise GraphValidationError("Workflow graph contains a dependency cycle.")
