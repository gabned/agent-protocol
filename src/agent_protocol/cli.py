"""Read-only engine CLI. Authorized host writes use the same typed evaluator."""

from __future__ import annotations

import argparse
import json
import sys

from .audit import reconcile
from .documents import select
from .ledger import exact
from .lifecycle import evaluate, freshness
from .qualification import ci_evidence, verify_protocol_candidate


def dispatch(command, value):
    if command == "explain":
        exact(value, "state request observation authority", "explain input")
        return evaluate(**value)
    if command == "freshness":
        exact(value, "evidence current", "freshness input")
        return freshness(**value)
    if command == "qualify-ci":
        exact(value, "inventory repository head accepted_policy", "CI input")
        return ci_evidence(**value)
    if command == "qualify-pr":
        exact(
            value, "collection accepted_profile expected_profile_digest", "PR qualification input"
        )
        return verify_protocol_candidate(**value)
    if command == "documents":
        exact(value, "root manifest accepted_digest phase host workstream", "document input")
        return select(**value)
    if command == "audit":
        exact(value, "scope rows accepted_scope_digest release_revision", "audit input")
        return reconcile(**value)
    raise ValueError("Unsupported engine operation")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=["explain", "freshness", "qualify-ci", "qualify-pr", "documents", "audit"],
    )
    args = parser.parse_args(argv)
    try:
        value = json.load(sys.stdin)
        result = dispatch(args.command, value)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(json.dumps({"result": "REFUSED", "reason": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
