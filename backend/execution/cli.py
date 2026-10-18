import argparse
import json
import logging

from execution.config import Settings
from execution.dispatch import EmulatorPump, Reconciler, reconcile_decision, revoke_access
from execution.runtime import Runtime
from tools.commands import checked_id, project_path


def main():
    parser = argparse.ArgumentParser(description="VibeShorts application and operator commands")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=8000)
    sub.add_parser("worker")
    sub.add_parser("sweep")
    sub.add_parser("preflight-paid", help="Check local paid-smoke configuration without cloud calls")
    inspect = sub.add_parser("inspect-job")
    inspect.add_argument("project_id")
    inspect.add_argument("job_id")
    reconcile = sub.add_parser("reconcile")
    reconcile.add_argument("project_id")
    reconcile.add_argument("job_id")
    reconcile.add_argument("--amount-micros", type=int, required=True)
    reconcile.add_argument("--evidence", required=True)
    reconcile.add_argument("--operator", required=True)
    revoke = sub.add_parser("revoke-access")
    revoke.add_argument("uid")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.command == "preflight-paid":
        from execution.preflight import paid_smoke_preflight

        result = paid_smoke_preflight()
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if result["ready"] else 1)
    if args.command == "serve":
        import uvicorn

        host = "127.0.0.1" if Settings().local_live else "0.0.0.0"
        uvicorn.run("api.main:create_app", factory=True, host=host, port=args.port)
        return
    runtime = Runtime.create()
    if args.command == "worker":
        if runtime.commands.settings.mode != "emulator" and not runtime.commands.settings.local_live:
            parser.error("Production workers use authenticated Pub/Sub push endpoints")
        EmulatorPump(runtime.commands, runtime.worker).run()
    elif args.command == "sweep":
        print(json.dumps({"recovered": Reconciler(runtime.commands).sweep()}))
    elif args.command == "inspect-job":
        document = runtime.commands.repo.get(project_path(args.project_id, "jobs", args.job_id))
        print(json.dumps(document, indent=2))
    elif args.command == "reconcile":
        reconcile_decision(
            runtime.commands, args.project_id, args.job_id, args.amount_micros, args.evidence, args.operator
        )
        print(json.dumps({"reconciled": args.job_id}))
    elif args.command == "revoke-access":
        revoke_access(runtime.commands, checked_id(args.uid))
        print(json.dumps({"access_revoked": args.uid}))
