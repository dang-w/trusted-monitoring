"""Run manifests.

Every run gets one manifest in `manifests/<run_id>.json`, written on the host by the harness
process, including runs that fail or are interrupted. The manifest is the entry in the ledger:
it names the code, the model files, the server settings and the sha256 of each log, so that a
log published later can be checked against it and no run can be left out afterwards.

    python -m tm.manifest --run-id ID [--note TEXT]      (re)build the manifest of logs/<ID>/

A manifest holds no secret, no absolute path and no host name. `write_manifest` refuses to
write one that contains the home directory or the contents of the key file.
"""

from __future__ import annotations

import argparse
import configparser
import datetime as dt
import hashlib
import json
import platform
import re
import subprocess
import sys
import urllib.request
from importlib import metadata
from pathlib import Path
from typing import Any

from tm.machine import DATASET, MODEL_PREFIX, Machine, machine

SCHEMA = 1
REPO = Path(__file__).resolve().parent.parent
LLAMA_VERSION = re.compile(
    r"version: (?P<version>\S+) \(build (?P<build>\d+), commit (?P<commit>[0-9a-f]+)\)"
)
# Server-side defaults that decide sampling when a request does not set them.
SAMPLING_KEYS = ("temperature", "top_k", "top_p", "min_p", "repeat_penalty", "n_predict", "seed")


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_output(*argv: str, cwd: Path | None = None, with_stderr: bool = False) -> str | None:
    """Output of a command, or None if it is missing or fails."""
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30, cwd=cwd, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout + result.stderr if with_stderr else result.stdout


# ---------------------------------------------------------------- pure parsers


def parse_presets(text: str) -> dict[str, dict[str, str]]:
    """llama-server preset file -> {model id: {key: value}}, with the `[*]` defaults applied."""
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.read_string("[__top__]\n" + text)
    defaults = dict(parser["*"]) if parser.has_section("*") else {}
    return {
        section: defaults | dict(parser[section])
        for section in parser.sections()
        if section not in ("__top__", "*")
    }


def parse_checksums(text: str) -> dict[str, str]:
    """`shasum -a 256` list -> {relative path: sha256}."""
    checksums: dict[str, str] = {}
    for line in text.splitlines():
        digest, _, name = line.partition(" ")
        name = name.strip().lstrip("*")
        if len(digest) == 64 and name:
            checksums[name] = digest
    return checksums


def parse_llama_version(text: str) -> dict[str, Any] | None:
    match = LLAMA_VERSION.search(text)
    if not match:
        return None
    return {"version": match["version"], "build": int(match["build"]), "commit": match["commit"]}


def model_ids(log_headers: list[dict[str, Any]]) -> list[str]:
    """Server model ids that the logs name, as the main model or in a model role."""
    names: set[str] = set()
    for header in log_headers:
        names.add(header["model"])
        names.update(role["model"] for role in header.get("model_roles", {}).values())
    # "none/none" is Inspect's placeholder when a task names its models only through roles.
    return sorted(name.removeprefix(MODEL_PREFIX) for name in names if name and name != "none/none")


def model_record(
    model_id: str, presets: dict[str, dict[str, str]], checksums: dict[str, str]
) -> dict[str, Any]:
    """File name and sha256 of a model's weights. The sha256 comes from the checksum list."""
    preset = presets.get(model_id)
    if preset is None or "model" not in preset:
        return {"id": model_id, "file": None, "sha256": None, "note": "no preset with this id"}
    path = preset["model"]
    for relative, digest in checksums.items():
        if path.endswith("/" + relative):
            return {"id": model_id, "file": Path(relative).name, "sha256": digest}
    return {"id": model_id, "file": Path(path).name, "sha256": None, "note": "not in the checksum list"}


def slot_settings(preset: dict[str, str]) -> dict[str, int | None]:
    def number(key: str) -> int | None:
        value = preset.get(key)
        return int(value) if value is not None and value.isdigit() else None

    return {
        "parallel": number("parallel"),
        "kv_unified_per_slot": number("kv-unified-per-slot"),
        "ctx_size": number("c"),
        "n_predict": number("n-predict"),
    }


# ---------------------------------------------------------------- facts from the machine


def git_state(repo: Path) -> dict[str, Any]:
    status = run_output("git", "status", "--porcelain", cwd=repo)
    return {
        "commit": (run_output("git", "rev-parse", "HEAD", cwd=repo) or "").strip() or None,
        "dirty": bool(status.strip()) if status is not None else None,
    }


def versions(repo: Path) -> dict[str, Any]:
    def package(name: str) -> str | None:
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            return None

    lock = repo / "uv.lock"
    return {
        "python": platform.python_version(),
        "inspect_ai": package("inspect-ai"),
        "control_arena": package("control-arena"),
        "uv_lock_sha256": sha256_file(lock) if lock.exists() else None,
    }


def switch_log_entries(path: Path, run_id: str) -> list[dict[str, Any]]:
    """Records of the mode-switch log that name this run."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    entries = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and entry.get("run_id") == run_id:
            entries.append(entry)
    return entries


def server_settings(base_url: str, key: str | None, model_id: str) -> dict[str, Any] | None:
    """Slot count, context and sampling defaults of a loaded model, from the server. Best effort."""
    root = base_url.removesuffix("/v1")
    request = urllib.request.Request(f"{root}/props?model={model_id}&autoload=false")
    if key:
        request.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            props = json.load(response)
    except (OSError, ValueError):
        return None
    settings = props.get("default_generation_settings", {})
    params = settings.get("params", {})
    return {
        "total_slots": props.get("total_slots"),
        "n_ctx": settings.get("n_ctx"),
        "build_info": props.get("build_info"),
        "sampling_defaults": {k: params.get(k) for k in SAMPLING_KEYS},
    }


def loaded_models(base_url: str, key: str | None) -> list[str]:
    """Ids of the models that the router has in memory now. Best effort."""
    request = urllib.request.Request(f"{base_url}/models")
    if key:
        request.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            data = json.load(response).get("data", [])
    except (OSError, ValueError):
        return []
    return [m["id"] for m in data if m.get("status", {}).get("value") == "loaded"]


def image_record(name: str) -> dict[str, Any]:
    """Identity of one container image. Needs the Docker daemon, and the image must still exist."""
    out = run_output("docker", "image", "inspect", name, "--format", "{{json .}}")
    if out is None:
        return {"name": name, "id": None, "note": "docker image inspect failed"}
    info = json.loads(out)
    return {
        "name": name,
        "id": info.get("Id"),
        "repo_digests": info.get("RepoDigests") or [],
        "architecture": info.get("Architecture"),
    }


def log_headers(log_dir: Path) -> list[dict[str, Any]]:
    """One record per .eval file: identity, outcome and the request-side sampling configuration."""
    from inspect_ai.log import read_eval_log  # imported here so that the parsers need no Inspect

    records = []
    for path in sorted(log_dir.glob("*.eval")):
        record: dict[str, Any] = {
            "file": path.name,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        try:
            log = read_eval_log(str(path), header_only=True)
        except Exception as e:  # a log cut off by a kill is still a log of this run
            record |= {"status": "unreadable", "error": type(e).__name__, "model": None}
            records.append(record)
            continue
        roles = log.eval.model_roles or {}
        record |= {
            "status": log.status,
            "task": log.eval.task,
            "model": log.eval.model,
            # request-side sampling settings of each role (temperature, seed, max_tokens, ...)
            "model_roles": {
                role: {"model": config.model, "config": config.config.model_dump(exclude_none=True)}
                for role, config in roles.items()
            },
            "samples": log.eval.dataset.samples,
            "completed_samples": log.results.completed_samples if log.results else None,
            "generate_config": log.eval.model_generate_config.model_dump(exclude_none=True),
            "eval_config": log.eval.config.model_dump(exclude_none=True),
            "sandbox": log.eval.sandbox.model_dump(exclude_none=True) if log.eval.sandbox else None,
            "inspect_run_id": log.eval.run_id,
            # the state of the repository as Inspect saw it when the run started
            "revision": log.eval.revision.model_dump(include={"commit", "dirty"})
            if log.eval.revision
            else None,
            "started": log.stats.started_at or None,
            "completed": log.stats.completed_at or None,
        }
        records.append(record)
    return records


# ---------------------------------------------------------------- build and write


def build_manifest(
    run_id: str,
    *,
    started: str | None,
    ended: str | None,
    status: str,
    exit_code: int | None,
    command: list[str],
    images: list[dict[str, Any]] | None,
    repo_state: dict[str, Any] | None = None,
    servers: dict[str, dict[str, Any]] | None = None,
    note: str | None = None,
    repo: Path = REPO,
    on: Machine | None = None,
) -> dict[str, Any]:
    on = on or machine()
    log_dir = repo / "logs" / run_id
    logs = log_headers(log_dir) if log_dir.is_dir() else []
    for record in logs:
        record["dataset_path"] = f"runs/{run_id}/{record['file']}"

    presets_text = on.presets.read_text() if on.presets.exists() else None
    presets = parse_presets(presets_text) if presets_text is not None else {}
    checksums = parse_checksums(on.model_checksums.read_text()) if on.model_checksums.exists() else {}
    used = model_ids([r for r in logs if r.get("model")])
    key = on.key_file.read_text().strip() if on.key_file.exists() else None

    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "started": started,
        "ended": ended,
        "status": status,
        "exit_code": exit_code,
        "command": command,
        "note": note,
        "repo": repo_state if repo_state is not None else git_state(repo),
        "versions": versions(repo),
        # llama-server prints its version on stderr
        "llama_cpp": parse_llama_version(
            run_output(str(on.llama_server), "--version", with_stderr=True) or ""
        ),
        "presets": {
            "file": on.presets.name,
            "sha256": hashlib.sha256(presets_text.encode()).hexdigest() if presets_text is not None else None,
        },
        "models": [
            model_record(model_id, presets, checksums)
            | {"slots": slot_settings(presets.get(model_id, {}))}
            # read while the model was loaded (the router keeps one model in memory), else read now
            | {"server": (servers or {}).get(model_id) or server_settings(on.base_url, key, model_id)}
            for model_id in used
        ],
        "container_images": images,
        "mode_switch_log": switch_log_entries(on.switch_log, run_id),
        "dataset": DATASET,
        "logs": logs,
    }


def write_manifest(manifest: dict[str, Any], repo: Path = REPO, on: Machine | None = None) -> Path:
    on = on or machine()
    text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if str(Path.home()) in text:
        raise ValueError("the manifest contains the home directory path; it must hold no absolute path")
    if on.key_file.exists() and (key := on.key_file.read_text().strip()) and key in text:
        raise ValueError("the manifest contains the API key")
    path = repo / "manifests" / f"{manifest['run_id']}.json"
    path.parent.mkdir(exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(text)
    temporary.replace(path)
    return path


def refresh_logs(run_id: str, logs: list[dict[str, Any]], note: str | None) -> int:
    """Read the log headers again into a manifest that was written at run time.

    Everything that was recorded during the run stays as it is. The sha256 of every log must be
    the one already in the manifest: a refresh never accepts a changed log.
    """
    path = REPO / "manifests" / f"{run_id}.json"
    manifest = json.loads(path.read_text())
    recorded = {r["file"]: r["sha256"] for r in manifest["logs"]}
    if recorded != {r["file"]: r["sha256"] for r in logs}:
        print(
            "the logs are not the ones in the manifest (name or sha256 differs); nothing written",
            file=sys.stderr,
        )
        return 1
    for record in logs:
        record["dataset_path"] = f"runs/{run_id}/{record['file']}"
    known = {m["id"]: m for m in manifest["models"]}
    manifest["models"] = [known[m] for m in model_ids([r for r in logs if r.get("model")]) if m in known]
    manifest["logs"] = logs
    manifest["note"] = " ".join(filter(None, [manifest.get("note"), note]))
    manifest["log_headers_refreshed"] = utc_now()
    print(write_manifest(manifest).relative_to(REPO))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="(Re)build the manifest of the logs in logs/<run-id>/.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--note", help="free text, for example why the manifest was built after the run")
    parser.add_argument(
        "--refresh-logs",
        action="store_true",
        help="keep the manifest written at run time and read only the log headers again",
    )
    args = parser.parse_args()
    logs = log_headers(REPO / "logs" / args.run_id)
    if not logs:
        print(f"no .eval file in logs/{args.run_id}/", file=sys.stderr)
        return 1
    if args.refresh_logs:
        return refresh_logs(args.run_id, logs, args.note)
    manifest = build_manifest(
        args.run_id,
        started=min((r["started"] for r in logs if r.get("started")), default=None),
        ended=max((r["completed"] for r in logs if r.get("completed")), default=None),
        status="rebuilt-after-run",
        exit_code=None,
        command=[],
        images=None,
        note=args.note,
        # the repository has moved on since the run; the log header has the state at run time
        repo_state=next((r["revision"] for r in logs if r.get("revision")), {"commit": None, "dirty": None}),
    )
    print(write_manifest(manifest).relative_to(REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
