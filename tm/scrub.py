"""Scrub check: a log must hold nothing that may not be published.

    python -m tm.scrub RUN_ID [RUN_ID ...]       check every .eval file in logs/<RUN_ID>/
    python -m tm.scrub --file PATH [...]          check the given .eval files

An Inspect `.eval` file is a zip archive (its members are zstd-compressed). Each member is
unpacked and the check fails on any of:

- key material, found by gitleaks with the repository's .gitleaks.toml;
- a home-directory path (/Users/..., /home/...);
- a tailnet address (the 100.64/10 range);
- a host name that is not the research machine's: any `.local` or `.ts.net` name, and any
  name in the local denylist file (a file outside the repository, one name per line). One
  exemption: a cgroup v2 file name under `/sys/fs/cgroup/` (`memory.events.local`,
  `cpu.stat.local`, ...) is a file, not a host (a sandbox listing put them in a scorer's
  output, `e3-gen-attack-3` sample 79);
- the contents of the local key files (the model server key and the dataset token).

Exit 0: every file is clean. Exit 1: at least one finding, listed on stderr. The push script
runs this first and never uploads a file that failed.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from tm.machine import machine
from tm.manifest import REPO

# zstd (method 93) support for zipfile; without it the check fails on such an archive, the safe direction
with contextlib.suppress(ImportError):
    import zipfile_zstd  # noqa: F401

HOME_PATH = re.compile(rb"/(?:Users|home)/[A-Za-z0-9._-]+/")
TAILNET_ADDRESS = re.compile(rb"\b100\.(?:6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.[0-9]{1,3}\.[0-9]{1,3}\b")
LOCAL_NAME = re.compile(rb"\b[A-Za-z0-9-]+\.(?:local|ts\.net)\b")
ALLOWED_HOST = b"research-mini"
# cgroup v2 files whose names end in `.local` (`memory.events.local`, `cpu.stat.local`,
# `hugetlb.*.events.local`), only as the last component of a path under /sys/fs/cgroup/
CGROUP_FILE = re.compile(
    rb"/sys/fs/cgroup(?:/[A-Za-z0-9_.-]+)*/[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*\.(?:events|stat)\.local\b"
)
DENYLIST_FILE = Path(
    os.environ.get("TM_HOST_DENYLIST", "~/.config/trusted-monitoring/host-denylist.txt")
).expanduser()


@dataclass
class Finding:
    file: str
    member: str
    rule: str
    detail: str


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    files: int = 0

    @property
    def clean(self) -> bool:
        return not self.findings


def secrets() -> list[bytes]:
    """The exact contents of the local key files, when they exist."""
    on = machine()
    token = Path("~/.config/huggingface/trusted-monitoring.token").expanduser()
    values = []
    for path in (on.key_file, token):
        try:
            value = path.read_bytes().strip()
        except OSError:
            continue
        if value:
            values.append(value)
    return values


def host_denylist() -> list[bytes]:
    try:
        lines = DENYLIST_FILE.read_text().splitlines()
    except OSError:
        return []
    return [line.strip().encode() for line in lines if line.strip() and not line.startswith("#")]


def check_bytes(
    data: bytes, *, known_secrets: list[bytes], denied_hosts: list[bytes]
) -> list[tuple[str, str]]:
    """Pure check of one member's bytes: (rule, detail) for each finding, with no secret in the detail."""
    found: list[tuple[str, str]] = []
    for match in HOME_PATH.finditer(data):
        found.append(("home-directory path", match.group().decode(errors="replace")))
    for match in TAILNET_ADDRESS.finditer(data):
        found.append(("tailnet address", match.group().decode(errors="replace")))
    cgroup_files = {m.end() for m in CGROUP_FILE.finditer(data)}
    for match in LOCAL_NAME.finditer(data):
        name = match.group()
        if name.startswith(ALLOWED_HOST + b"."):  # research-mini.local is the research machine itself
            continue
        if match.end() in cgroup_files:  # the `.local` ends a cgroup file path, not a host name
            continue
        found.append(("host name", name.decode(errors="replace")))
    for host in denied_hosts:
        if host in data:
            found.append(("host name (denylist)", host.decode(errors="replace")))
    for secret in known_secrets:
        if secret in data:
            found.append(("contents of a local key file", "(not shown)"))
    # one finding per (rule, detail): the same path can appear thousands of times
    unique: dict[tuple[str, str], None] = dict.fromkeys(found)
    return list(unique)


def gitleaks(directory: Path) -> list[str]:
    """Rule ids and files that gitleaks flags in the directory, with the repository's config."""
    result = subprocess.run(
        [
            "gitleaks",
            "dir",
            str(directory),
            "--config",
            str(REPO / ".gitleaks.toml"),
            "--no-banner",
            "--redact",
            "--exit-code",
            "1",
            "--report-format",
            "json",
            "--report-path",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return []
    if result.returncode != 1:
        return [f"gitleaks did not run: {result.stderr.strip()[-200:]}"]
    try:
        leaks = json.loads(result.stdout or "[]")
    except ValueError:
        return ["gitleaks reported leaks but its report could not be read"]
    return [f"{leak.get('RuleID')} in {Path(leak.get('File', '?')).name}" for leak in leaks]


def check_file(path: Path, report: Report, *, known_secrets: list[bytes], denied_hosts: list[bytes]) -> None:
    report.files += 1
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as e:
        report.findings.append(Finding(path.name, "", "not a readable zip archive", str(e)))
        return
    with tempfile.TemporaryDirectory(prefix="scrub-") as tmp:
        for member in archive.infolist():
            try:
                data = archive.read(member)
            except (NotImplementedError, zipfile.BadZipFile, RuntimeError) as e:
                report.findings.append(
                    Finding(path.name, member.filename, "member could not be unpacked", str(e))
                )
                continue
            for rule, detail in check_bytes(data, known_secrets=known_secrets, denied_hosts=denied_hosts):
                report.findings.append(Finding(path.name, member.filename, rule, detail))
            target = Path(tmp) / member.filename.replace("/", "__")
            target.write_bytes(data)
        for leak in gitleaks(Path(tmp)):
            report.findings.append(Finding(path.name, "", "gitleaks", leak))


def scrub(paths: list[Path]) -> Report:
    report = Report()
    known_secrets, denied_hosts = secrets(), host_denylist()
    for path in paths:
        check_file(path, report, known_secrets=known_secrets, denied_hosts=denied_hosts)
    return report


def run_logs(run_id: str) -> list[Path]:
    return sorted((REPO / "logs" / run_id).glob("*.eval"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check that log files hold nothing that may not be published."
    )
    parser.add_argument("run_ids", nargs="*")
    parser.add_argument("--file", action="append", default=[], type=Path, help="an .eval file to check")
    args = parser.parse_args()
    paths = [*args.file, *(p for run_id in args.run_ids for p in run_logs(run_id))]
    if not paths:
        parser.error("give run ids or --file")
    report = scrub(paths)
    for f in report.findings:
        print(f"SCRUB {f.file} {f.member or '-'}: {f.rule}: {f.detail}", file=sys.stderr)
    verdict = "clean" if report.clean else "FAILED"
    print(f"scrub: {report.files} file(s), {len(report.findings)} finding(s): {verdict}")
    return 0 if report.clean else 1


if __name__ == "__main__":
    sys.exit(main())
