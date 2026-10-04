"""Publish the logs of runs to the Hugging Face dataset and verify them.

    python -m tm.publish RUN_ID [RUN_ID ...]

For each run: the scrub check must pass on every log, and the run must have a manifest whose
sha256 of each log equals the file on disk. Then the batch goes up in one dataset commit, each
log at the path its manifest names (`runs/<run_id>/<file>`). Each uploaded file is downloaded
again at that commit and its sha256 compared with the manifest. Only then is the manifest
updated with the dataset commit and the verification time.

A scrub failure publishes nothing from the batch and marks each failed run `scrub-failed` in
its manifest. The token is read from a file outside the repository and never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from huggingface_hub import CommitOperationAdd, HfApi, hf_hub_download

from tm.machine import DATASET
from tm.manifest import REPO, sha256_file, utc_now, write_manifest
from tm.scrub import run_logs, scrub

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")  # the log line per file is enough
TOKEN_FILE = Path("~/.config/huggingface/trusted-monitoring.token").expanduser()


def token() -> str:
    value = TOKEN_FILE.read_text().strip()
    if not value:
        raise SystemExit(f"publish: the token file {TOKEN_FILE} is empty")
    return value


def manifest_of(run_id: str) -> dict:
    path = REPO / "manifests" / f"{run_id}.json"
    if not path.exists():
        raise SystemExit(
            f"publish: run {run_id} has no manifest; a run without a manifest is never published"
        )
    return json.loads(path.read_text())


def check_against_manifest(run_id: str, manifest: dict) -> list[tuple[Path, str, str]]:
    """(local file, dataset path, sha256) for each log, after the file on disk matches the manifest."""
    recorded = {r["file"]: r for r in manifest["logs"]}
    files = run_logs(run_id)
    if not files:
        raise SystemExit(f"publish: no log in logs/{run_id}/")
    if {f.name for f in files} != set(recorded):
        raise SystemExit(f"publish: the logs in logs/{run_id}/ are not the ones in the manifest")
    batch = []
    for path in files:
        digest = sha256_file(path)
        if digest != recorded[path.name]["sha256"]:
            raise SystemExit(f"publish: {path.name} differs from its manifest sha256; nothing published")
        batch.append((path, recorded[path.name]["dataset_path"], digest))
    return batch


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish the logs of runs to the dataset and verify them.")
    parser.add_argument("run_ids", nargs="+")
    args = parser.parse_args()

    manifests = {run_id: manifest_of(run_id) for run_id in args.run_ids}
    already = [r for r, m in manifests.items() if all(log.get("published") for log in m["logs"])]
    if already:
        print(f"publish: already published, skipped: {', '.join(already)}")
    pending = [r for r in args.run_ids if r not in already]
    if not pending:
        return 0

    # 1. scrub, per run, so that one bad run does not hide the state of the others
    failed = []
    for run_id in pending:
        report = scrub(run_logs(run_id))
        for f in report.findings:
            print(f"SCRUB {run_id} {f.file} {f.member or '-'}: {f.rule}: {f.detail}", file=sys.stderr)
        if not report.clean:
            failed.append(run_id)
            manifest = manifests[run_id]
            manifest["status"] = "scrub-failed"
            manifest["scrub"] = {"checked": utc_now(), "findings": len(report.findings)}
            write_manifest(manifest)
    for run_id in pending:
        if run_id not in failed and manifests[run_id].get("status") == "scrub-failed":
            # A run marked scrub-failed earlier (an allowlist or a rule changed since) is clean now.
            manifest = manifests[run_id]
            previous = manifest.get("scrub", {})
            manifest["status"] = "completed"
            manifest["scrub"] = {"checked": utc_now(), "findings": 0, "previous": previous}
    if failed:
        print(
            f"publish: scrub FAILED for {', '.join(failed)}; nothing published from this batch",
            file=sys.stderr,
        )
        return 1

    # 2. compare every log with its manifest, then one commit for the batch
    operations, plan = [], {}
    for run_id in pending:
        batch = check_against_manifest(run_id, manifests[run_id])
        plan[run_id] = batch
        for path, dataset_path, _ in batch:
            operations.append(CommitOperationAdd(path_in_repo=dataset_path, path_or_fileobj=str(path)))
    api = HfApi(token=token())
    commit = api.create_commit(
        repo_id=DATASET,
        repo_type="dataset",
        operations=operations,
        commit_message=f"Logs of {len(pending)} run(s): {', '.join(pending)}",
    )
    print(f"publish: uploaded {len(operations)} file(s) in dataset commit {commit.oid}")

    # 3. download each file again at that commit and compare with the manifest
    verified_at = utc_now()
    with tempfile.TemporaryDirectory(prefix="publish-") as tmp:
        for run_id, batch in plan.items():
            manifest = manifests[run_id]
            for path, dataset_path, digest in batch:
                local = hf_hub_download(
                    DATASET,
                    dataset_path,
                    repo_type="dataset",
                    revision=commit.oid,
                    cache_dir=tmp,
                    token=api.token,
                )
                got = sha256_file(Path(local))
                if got != digest:
                    print(
                        f"publish: VERIFY FAILED {dataset_path}: "
                        f"downloaded {got[:12]}, manifest {digest[:12]}",
                        file=sys.stderr,
                    )
                    return 1
                for log in manifest["logs"]:
                    if log["file"] == path.name:
                        log["published"] = {
                            "dataset": DATASET,
                            "dataset_commit": commit.oid,
                            "url": f"https://huggingface.co/datasets/{DATASET}/blob/{commit.oid}/{dataset_path}",
                            "verified": verified_at,
                        }
                print(f"publish: verified {dataset_path} ({digest[:12]})")
            write_manifest(manifest)
    print("publish: done; manifests updated, commit them")
    return 0


if __name__ == "__main__":
    sys.exit(main())
