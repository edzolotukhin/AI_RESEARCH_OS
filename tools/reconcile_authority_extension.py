from __future__ import annotations

import argparse
import json

from application.composition_root import create_application_container


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile one failed authority extension.")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--extension-id", required=True)
    parser.add_argument("--expected-workflow-id", required=True)
    parser.add_argument("--reason", required=True, help="Bounded operator reason")
    parser.add_argument("--failure-class", default="RuntimeError")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    container = create_application_container()
    try:
        result = container.authority_extension_service.reconcile_failed_extension(
            project_id=args.project_id, extension_id=args.extension_id,
            expected_workflow_run_id=args.expected_workflow_id,
            failure_class=args.failure_class, reason=args.reason,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, sort_keys=True))
        return 0 if result.get("ok") else 2
    finally:
        container.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
