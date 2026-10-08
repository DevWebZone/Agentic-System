from __future__ import annotations

import re
from dataclasses import dataclass

from app.orchestration.graph import GraphNode, validate_graph
from app.orchestration.schemas import WorkflowNodeRequest

CONCERN_ORDER = ("api", "database", "security", "analytics", "testing", "docs")
HIGH_IMPACT_CONCERNS = {"api", "database", "security"}
ALWAYS_INCLUDED_CONCERNS = {"testing", "docs"}
CONCERN_PATTERNS = {
    "api": [r"\balias\b", r"\bendpoint\b", r"\bredirect\b", r"\bapi\b"],
    "database": [
        r"\bschema\b",
        r"\bmigration\b",
        r"\btable\b",
        r"\bstore\b",
        r"\bpersist\w*\b",
    ],
    "security": [
        r"\bauth\w*\b",
        r"\bprivate\b",
        r"\binternal\b",
        r"\bvalidation\b",
        r"\brate\s+limit\b",
        r"\bmalware\b",
        r"\babuse\b",
    ],
    "analytics": [r"\bclick\b", r"\banalytics\b", r"\breferrer\b"],
}


@dataclass(frozen=True)
class PlanResult:
    nodes: list[WorkflowNodeRequest]
    detected_concerns: list[str]
    rationale: dict[str, object]


@dataclass(frozen=True)
class PlannedNodeSpec:
    node_key: str
    node_type: str
    dependency_keys: tuple[str, ...]
    concern_tags: tuple[str, ...]
    max_retries: int
    requires_approval: bool
    inclusion_reason: str

    def to_request(self) -> WorkflowNodeRequest:
        return WorkflowNodeRequest(
            node_key=self.node_key,
            node_type=self.node_type,
            dependency_keys=list(self.dependency_keys),
            concern_tags=list(self.concern_tags),
            max_retries=self.max_retries,
            requires_approval=self.requires_approval,
        )

    def rationale_entry(self) -> dict[str, object]:
        return {
            "node_key": self.node_key,
            "node_type": self.node_type,
            "requires_approval": self.requires_approval,
            "dependency_keys": list(self.dependency_keys),
            "concern_tags": list(self.concern_tags),
            "reason": self.inclusion_reason,
        }


def plan_graph(requirement: str) -> PlanResult:
    detected_concerns = detect_concerns(requirement)
    node_specs, excluded_nodes = _build_node_specs(detected_concerns)
    nodes = [spec.to_request() for spec in node_specs]
    try:
        validate_graph(
            GraphNode(key=node.node_key, dependencies=tuple(node.dependency_keys)) for node in nodes
        )
    except ValueError as exc:
        raise ValueError(f"Planner produced an invalid workflow graph: {exc}") from exc

    return PlanResult(
        nodes=nodes,
        detected_concerns=detected_concerns,
        rationale={
            "detected_concerns": detected_concerns,
            "included_nodes": [spec.rationale_entry() for spec in node_specs],
            "excluded_nodes": excluded_nodes,
        },
    )


def detect_concerns(requirement: str) -> list[str]:
    normalized = requirement.lower()
    concerns = set(ALWAYS_INCLUDED_CONCERNS)
    for concern, patterns in CONCERN_PATTERNS.items():
        if any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in patterns):
            concerns.add(concern)
    return [concern for concern in CONCERN_ORDER if concern in concerns]


def _build_node_specs(concerns: list[str]) -> tuple[list[PlannedNodeSpec], list[dict[str, str]]]:
    concern_set = set(concerns)
    high_impact = sorted(concern_set & HIGH_IMPACT_CONCERNS)
    planning_tags = tuple(concerns)
    node_specs: list[PlannedNodeSpec] = [
        _node(
            "requirements",
            "requirements",
            (),
            planning_tags,
            "Capture the original requirement.",
        ),
        _node(
            "ambiguity-check",
            "planning",
            ("requirements",),
            planning_tags,
            "Review the normalized requirement for ambiguity before design proceeds.",
        ),
        _node(
            "architecture",
            "architecture",
            ("ambiguity-check",),
            planning_tags,
            "Establish the design boundary for the requested concerns.",
        ),
        _node(
            "task-decomposition",
            "planning",
            ("architecture",),
            planning_tags,
            "Break the change into governed execution stages.",
        ),
    ]

    planning_branch_dependencies = ("task-decomposition",)
    if high_impact:
        node_specs.append(
            _node(
                "risk-review",
                "risk_review",
                planning_branch_dependencies,
                tuple(high_impact),
                "Security, API, or database concerns require explicit risk review.",
            )
        )

    node_specs.extend(
        [
            _node(
                "test-plan",
                "testing",
                planning_branch_dependencies,
                ("testing",),
                "Testing is always required before implementation.",
            ),
            _node(
                "implementation-plan",
                "planning",
                planning_branch_dependencies,
                planning_tags,
                "Implementation planning is always required before changes are proposed.",
            ),
        ]
    )

    join_dependencies = ["test-plan", "implementation-plan"]
    excluded_nodes: list[dict[str, str]] = []
    if high_impact:
        join_dependencies.append("risk-review")
    else:
        excluded_nodes.append(
            {
                "node_key": "risk-review",
                "reason": "No security, API, or database concerns were detected.",
            }
        )

    if "database" in concern_set:
        node_specs.append(
            _node(
                "migration-review",
                "risk_review",
                planning_branch_dependencies,
                ("database",),
                "Database changes require migration-specific approval before implementation.",
                requires_approval=True,
                max_retries=0,
            )
        )
        join_dependencies.append("migration-review")
    else:
        excluded_nodes.append(
            {"node_key": "migration-review", "reason": "No database concern was detected."}
        )

    if "analytics" in concern_set:
        node_specs.append(
            _node(
                "analytics-impact",
                "architecture",
                planning_branch_dependencies,
                ("analytics",),
                "Analytics requirements need an explicit impact review.",
            )
        )
        join_dependencies.append("analytics-impact")
    else:
        excluded_nodes.append(
            {"node_key": "analytics-impact", "reason": "No analytics concern was detected."}
        )

    node_specs.extend(
        [
            _node(
                "plan-sync",
                "planning",
                tuple(join_dependencies),
                planning_tags,
                "Synchronize the planning branch before approval or implementation work.",
            ),
            _node(
                "implementation-approval",
                "planning",
                ("plan-sync",),
                tuple(high_impact) or planning_tags,
                "Pause for approval when the planned implementation touches high-impact concerns.",
                requires_approval=bool(high_impact),
                max_retries=0 if high_impact else 2,
            ),
            _node(
                "implementation",
                "implementation",
                ("implementation-approval",),
                planning_tags,
                "Implementation follows the approved plan.",
            ),
            _node(
                "test-execution",
                "testing",
                ("implementation",),
                ("testing",),
                "Execute tests after implementation is available.",
            ),
            _node(
                "documentation",
                "documentation",
                ("implementation",),
                ("docs",),
                "Documentation always runs in parallel with test execution.",
            ),
            _node(
                "validation-sync",
                "planning",
                ("test-execution", "documentation"),
                ("testing", "docs"),
                "Join documentation and test execution before final validation.",
            ),
            _node(
                "validation",
                "validation",
                ("validation-sync",),
                ("testing",),
                "Validation is the final automated gate before release approval.",
            ),
            _node(
                "release-approval",
                "release",
                ("validation",),
                planning_tags,
                "Release always requires approval after validation passes.",
                requires_approval=True,
                max_retries=0,
            ),
            _node(
                "final-summary",
                "summary",
                ("release-approval",),
                planning_tags,
                "Summarize the workflow after release approval.",
            ),
        ]
    )
    return node_specs, excluded_nodes


def _node(
    node_key: str,
    node_type: str,
    dependencies: tuple[str, ...],
    concern_tags: tuple[str, ...],
    inclusion_reason: str,
    *,
    requires_approval: bool = False,
    max_retries: int = 2,
) -> PlannedNodeSpec:
    return PlannedNodeSpec(
        node_key=node_key,
        node_type=node_type,
        dependency_keys=dependencies,
        concern_tags=concern_tags,
        max_retries=max_retries,
        requires_approval=requires_approval,
        inclusion_reason=inclusion_reason,
    )