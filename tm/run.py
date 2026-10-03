"""Run one Inspect command as a recorded run.

    python -m tm.run --run-id ID -- eval smoke/task.py --model openai-api/llama-cpp/<model id>

What it adds to a plain `inspect` call:

- the API key is read from the key file and given to Inspect's `openai-api` provider;
- the logs go to `logs/<run-id>/`;
- the machine is kept awake for the length of the run (`caffeinate`, when it exists);
- `docker ps` is sampled to record which container images the run used;
- `manifests/<run-id>.json` is always written, also when the run fails or is interrupted.

A run id is used once. The one exception is `--resume`: a run that was interrupted (or failed)
continues under its run id with `inspect eval-retry logs/<run-id>/<log>.eval`, which keeps the
finished samples and runs the rest. The manifest of the first attempt is kept under `attempts`.

The mode switch of the machine (interactive to research and back) is not done here; when the
same run id is given to that switch, its log lines appear in the manifest.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from tm.machine import machine
from tm.manifest import (
    REPO,
    build_manifest,
    git_state,
    image_record,
    loaded_models,
    run_output,
    server_settings,
    utc_now,
    write_manifest,
)

RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}")
POLL_SECONDS = 3
RESUMABLE = {"interrupted", "failed"}


def default_run_id() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def watch(
    images: dict[str, dict[str, Any]],
    servers: dict[str, dict[str, Any]],
    stop: threading.Event,
    base_url: str,
    key: str,
) -> None:
    """Record facts that exist only during the run.

    Each image of a running container, while the image still exists. The server settings of each
    model, while it is loaded: the router keeps one model in memory, so at the end of a run with
    two models only the last one can still be asked.
    """
    while not stop.wait(POLL_SECONDS):
        for name in (run_output("docker", "ps", "--format", "{{.Image}}") or "").split():
            if name not in images:
                images[name] = image_record(name)
        for model_id in loaded_models(base_url, key):
            if model_id not in servers and (settings := server_settings(base_url, key, model_id)):
                servers[model_id] = settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one Inspect command and write its manifest.")
    parser.add_argument("--run-id", default=default_run_id(), help="unique id of the run (default: UTC time)")
    parser.add_argument("--note", help="free text for the manifest")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="continue an interrupted or failed run under its run id (with inspect eval-retry)",
    )
    parser.add_argument("inspect_args", nargs=argparse.REMAINDER, help="-- followed by the inspect arguments")
    args = parser.parse_args()
    inspect_args = args.inspect_args[1:] if args.inspect_args[:1] == ["--"] else args.inspect_args

    if not RUN_ID.fullmatch(args.run_id):
        parser.error("the run id may hold letters, digits, '.', '_' and '-'")
    if not inspect_args:
        parser.error("give the inspect arguments after --")
    if "--log-dir" in inspect_args:
        parser.error("do not give --log-dir: the logs of a run go to logs/<run-id>/")
    manifest_path = REPO / "manifests" / f"{args.run_id}.json"
    previous: dict[str, Any] | None = None
    if manifest_path.exists():
        if not args.resume:
            parser.error(f"run id {args.run_id} already has a manifest; a run id is used once")
        previous = json.loads(manifest_path.read_text())
        if previous.get("status") not in RESUMABLE:
            parser.error(
                f"run {args.run_id} has status {previous.get('status')!r}; only {sorted(RESUMABLE)} resume"
            )
    elif args.resume:
        parser.error(f"run id {args.run_id} has no manifest to resume")

    on = machine()
    try:
        key = on.key_file.read_text().strip()
    except OSError as e:
        print(f"tm.run: cannot read the key file: {e.strerror}", file=sys.stderr)
        return 1

    log_dir = Path("logs") / args.run_id
    (REPO / log_dir).mkdir(parents=True, exist_ok=True)
    command = ["inspect", *inspect_args, "--log-dir", log_dir.as_posix()]
    environment = os.environ | {"LLAMA_CPP_API_KEY": key, "LLAMA_CPP_BASE_URL": on.base_url}
    inspect = Path(sys.executable).parent / "inspect"

    images: dict[str, dict[str, Any]] = {}
    servers: dict[str, dict[str, Any]] = {}
    stop = threading.Event()
    watcher = threading.Thread(target=watch, args=(images, servers, stop, on.base_url, key), daemon=True)
    interrupted = False
    started = utc_now()
    repo_state = git_state(REPO)  # before the run: the run itself adds files
    child = subprocess.Popen([str(inspect), *command[1:]], cwd=REPO, env=environment)

    def forward(signum: int, frame: object) -> None:
        nonlocal interrupted
        interrupted = True
        child.send_signal(signal.SIGINT)  # Inspect stops gracefully on SIGINT and closes its log

    signal.signal(signal.SIGINT, forward)
    signal.signal(signal.SIGTERM, forward)
    if caffeinate := shutil.which("caffeinate"):
        # A sidecar that ends with the child; wrapping the child would hide it from our signals.
        subprocess.Popen([caffeinate, "-dimsu", "-w", str(child.pid)])
    watcher.start()
    try:
        exit_code = child.wait()
    finally:
        stop.set()
        watcher.join(timeout=POLL_SECONDS + 30)

    if interrupted:
        status = "interrupted"
    elif exit_code == 0:
        status = "completed"
    else:
        status = "failed"
    manifest = build_manifest(
        args.run_id,
        started=started,
        ended=utc_now(),
        status=status,
        exit_code=exit_code,
        command=command,
        images=[images[name] for name in sorted(images)],
        repo_state=repo_state,
        servers=servers,
        note=args.note if args.note is not None else (previous or {}).get("note"),
        on=on,
    )
    if previous is not None:
        # The earlier attempts stay in the manifest, without their own attempt lists.
        attempts = previous.pop("attempts", [])
        manifest["attempts"] = [*attempts, previous]
    print(f"tm.run: {status}; manifest {write_manifest(manifest, on=on).relative_to(REPO)}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
