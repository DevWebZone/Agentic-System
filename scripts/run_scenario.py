"""Run a named engineering scenario without starting the HTTP server."""

import argparse
import json

from app.core.database import SessionLocal
from app.orchestration.observability import workflow_summary
from app.orchestration.scenarios import ScenarioRunner


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=["greenfield", "brownfield", "ambiguous"])
    arguments = parser.parse_args()

    with SessionLocal() as session:
        workflow = ScenarioRunner(session).run(arguments.scenario)
        print(json.dumps(workflow_summary(session, workflow), default=str, indent=2))


if __name__ == "__main__":
    main()