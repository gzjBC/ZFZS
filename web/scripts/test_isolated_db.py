"""Run the Web acceptance gate on a disposable local Docker PostgreSQL.

    python scripts/test_isolated_db.py --image postgres:17-alpine

The image must already be installed. No existing containers or volumes are used.
"""
import argparse
import os
import socket
import subprocess
import time
import uuid
from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1]
LABEL = "zfzs.integration-test"


def docker(*args, timeout=20, check=True):
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout, check=check)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", choices=("postgres:16-alpine", "postgres:17-alpine"), default="postgres:16-alpine")
    args = parser.parse_args()
    name = "zfzs-integration-" + uuid.uuid4().hex[:10]
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    created = False
    try:
        docker(
            "run", "--detach", "--rm", "--pull=never", "--name", name,
            "--label", f"{LABEL}=true", "--publish", f"127.0.0.1:{port}:5432",
            "--env", "POSTGRES_USER=anime", "--env", "POSTGRES_PASSWORD=zfzs_test_only",
            "--env", "POSTGRES_DB=anime_tracker_test", args.image,
        )
        created = True
        print(f"Created disposable {args.image} on loopback port {port}.", flush=True)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if docker("exec", name, "pg_isready", "-U", "anime", "-d", "anime_tracker_test", check=False).returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Disposable PostgreSQL did not become ready")
        environment = dict(os.environ)
        environment["TEST_DATABASE_URL"] = f"postgres://anime:zfzs_test_only@127.0.0.1:{port}/anime_tracker_test"
        environment["DATABASE_URL"] = environment["TEST_DATABASE_URL"]
        result = subprocess.run(["node", "scripts/check.mjs"], cwd=WEB_ROOT, env=environment, timeout=120)
        if result.returncode:
            raise SystemExit(result.returncode)
    finally:
        if created:
            label = docker("inspect", "--format", '{{index .Config.Labels "' + LABEL + '"}}', name, check=False)
            if label.returncode == 0 and label.stdout.strip() == "true":
                docker("stop", "--time", "3", name)
                print("Removed only the disposable ZFZS test container.", flush=True)


if __name__ == "__main__":
    main()
