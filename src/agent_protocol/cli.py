"""Protocol engine CLI; enrolled host operations use the same typed evaluator."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .audit import reconcile
from .documents import select
from .host import NativeGitHubHost
from .ledger import exact, require
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


HOST_COMMANDS = {
    "start": "START",
    "refresh": "REFRESH",
    "interrupt": "INTERRUPT",
    "resume": "RESUME",
    "handoff": "HANDOFF",
    "qualify": "QUALIFY",
    "integrate": "INTEGRATE",
    "reconcile": "RECONCILE",
    "reconcile-not-applied": "RECONCILE_NOT_APPLIED",
    "close": "CLOSE",
    "abandon": "ABANDON",
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "explain",
            "freshness",
            "qualify-ci",
            "qualify-pr",
            "documents",
            "audit",
            "state",
            *HOST_COMMANDS,
        ],
    )
    parser.add_argument(
        "--enrollment",
        type=Path,
        help="Independently approved operator enrollment, outside candidate checkouts",
    )
    args = parser.parse_args(argv)
    try:
        if args.enrollment is not None:
            require(
                args.command in {"explain", "state", *HOST_COMMANDS},
                "No host effect for this command",
            )
            host = NativeGitHubHost(json.loads(args.enrollment.read_text(encoding="utf-8")))
            if args.command == "state":
                host.journal.synchronize()
                state = host.journal.read()
                result = {
                    k: state[k]
                    for k in ("identity", "status", "owner", "tip", "head", "coordinates", "merge")
                }
                result["journal_events"] = len(state["events"])
                result["qualification_result"] = (state["qualification"] or {}).get(
                    "result", "NOT_RUN"
                )
            else:
                value = json.load(sys.stdin)
                if args.command == "explain":
                    result = host.host.explain(value)
                else:
                    require(
                        value["operation"] == HOST_COMMANDS[args.command],
                        "CLI/request operation mismatch",
                    )
                    result = host.host.operate(value)
        else:
            require(
                args.command not in {"state", *HOST_COMMANDS},
                "Independent operator enrollment required",
            )
            value = json.load(sys.stdin)
            result = dispatch(args.command, value)
        print(json.dumps(result, sort_keys=True))
        return 0
    except subprocess.SubprocessError:
        print(
            json.dumps(
                {
                    "result": "REFUSED",
                    "reason": "Host subprocess failed or timed out; reconcile before retry",
                    "reconciliation_required": True,
                }
            ),
            file=sys.stderr,
        )
        return 2
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(json.dumps({"result": "REFUSED", "reason": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
