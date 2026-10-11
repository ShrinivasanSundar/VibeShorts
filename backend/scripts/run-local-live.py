"""Supervise the local live stack and stop its children if a service exits."""

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[2]
    for port in (8000, 3000):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                listener.bind(("0.0.0.0", port))
            except OSError as exc:
                print(f"Cannot start dev:live: port {port} is unavailable ({exc}).", file=sys.stderr)
                print(
                    "Stop the existing npm run dev / dev:live stack with Ctrl+C, then retry.", file=sys.stderr
                )
                return 1
    if "--check-ports" in sys.argv:
        return 0

    processes = []

    def interrupt(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGINT, interrupt)
    executable = str(root / "backend/.venv/bin/vibeshorts")
    services = [
        ("API", [executable, "serve", "--port", "8000"], os.environ.copy()),
        ("worker", [executable, "worker"], os.environ.copy()),
        (
            "frontend",
            ["npm", "run", "dev", "--workspace", "frontend", "--", "--port", "3000"],
            dict(os.environ, NODE_ENV="development"),
        ),
    ]
    try:
        for name, command, env in services:
            processes.append((name, subprocess.Popen(command, cwd=root, env=env, start_new_session=True)))
        while True:
            for name, process in processes:
                code = process.poll()
                if code is not None:
                    print(
                        f"dev:live {name} exited ({code}); stopping the remaining services.", file=sys.stderr
                    )
                    return code or 1
            time.sleep(0.2)
    except KeyboardInterrupt:
        return 130
    finally:
        for _, process in processes:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for _, process in processes:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
