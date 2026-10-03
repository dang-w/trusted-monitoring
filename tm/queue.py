"""Queue runner: run the queued specs one at a time, unattended.

    scripts/run-queue run [--once] [--until ISO8601]        manual: everything that fits, or one spec
    scripts/run-queue run --window                         the nightly window (ends 06:30 local time)
    scripts/run-queue run --test-window MINUTES            a compressed window, for tests
    scripts/run-queue list                                  what is pending, running, done, failed
    scripts/run-queue check SPEC.yaml                       validate one spec

A spec is a YAML file in `queue/pending/`:

    estimated_minutes: 40                 # required; from the D12 timings times the sample count
    note: APPS honest, 20 samples         # optional; goes into the manifest
    inspect:                              # required; the arguments after `inspect`
      - eval
      - control/apps/task.py@apps_tm_honest
      - --limit
      - "20"

The run id is the file name without `.yaml`. For each spec, in order of age:

 1. `mini-mode research --run-id <id>` (a hold, a lease or a busy interactive router refuse it;
    the spec stays pending);
 2. the spec moves to `running/`; `python -m tm.run` runs it, under `caffeinate`, in `logs/<id>/`;
 3. the manifest is written by `tm.run`, also on a failure or an interruption;
 4. `tm.publish` scrubs the logs and pushes them (a scrub failure marks the run `scrub-failed`
    and the spec goes to `failed/`; the check is never skipped);
 5. the manifest and the queue move are committed and pushed;
 6. `mini-mode interactive`;
 7. one notification, one line in the graduation ledger.

A stop (SIGUSR1 from `mini-mode interactive --preempt`, SIGINT, SIGTERM, or the end of the
window) interrupts Inspect gracefully, puts the spec back into `pending/` with a resume marker,
records the interruption in the manifest, commits, and switches back. A spec with a resume
marker continues with `inspect eval-retry` on its partial log: the finished samples are kept.

A spec found in `running/` at start belongs to a runner that was killed. It goes back to
`pending/` with a resume marker; the box is restored first; its later clean run is the
kill-recovery test of the graduation bar.

A spec does not start when `estimated_minutes` plus a margin does not fit before the deadline
(the window end, or `--until`). On the router error "model limit reached" the run is retried
with back-off for up to 5 minutes.

Nothing here reads a secret: the key, the token and the ntfy topic are read by `tm.run`,
`tm.publish` and `mini-mode`.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from tm.manifest import REPO
from tm.run import RUN_ID

QUEUE = REPO / "queue"
STATES = ("pending", "running", "done", "failed")
STATE_DIR = Path("~/.local/state/pail").expanduser()
LOCK_FILE = STATE_DIR / "run-queue.lock"
GRADUATION_LOG = STATE_DIR / "graduation.jsonl"

WINDOW_END = dt.time(6, 30)  # local time (Europe/London on the box), decided 2026-10-02
MARGIN_MINUTES = 10  # the switch back, the publish and the commit after the last sample
BUSY_RETRY_SECONDS = 15 * 60  # the interactive router is in use: try again later in the window
STOP_GRACE_SECONDS = 300  # Inspect gets this long to close its log after SIGINT
MODEL_LIMIT_TEXT = "model limit reached"
MODEL_LIMIT_BACKOFF = (30, 60, 120, 90)  # seconds; sums to 5 minutes
TOOL_PATH = "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

MINI_MODE_EXIT = {0: "ok", 1: "failed", 2: "usage", 3: "hold", 4: "lease", 5: "busy"}


class SpecError(ValueError):
    """A spec file is not valid."""


@dataclass
class Spec:
    path: Path
    estimated_minutes: int
    inspect: list[str]
    note: str | None = None
    queued: str | None = None
    resume: dict[str, Any] | None = None
    attempts: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def run_id(self) -> str:
        return self.path.stem

    @property
    def state(self) -> str:
        return self.path.parent.name

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"estimated_minutes": self.estimated_minutes}
        if self.note is not None:
            data["note"] = self.note
        data["inspect"] = self.inspect
        if self.queued:
            data["queued"] = self.queued
        if self.resume:
            data["resume"] = self.resume
        if self.attempts:
            data["attempts"] = self.attempts
        data.update(self.extra)
        return data


# ---------------------------------------------------------------- small helpers


def now() -> dt.datetime:
    return dt.datetime.now().astimezone()


def log(message: str) -> None:
    print(f"{now().isoformat(timespec='seconds')} run-queue: {message}", flush=True)


def duration(seconds: float) -> str:
    seconds = int(seconds)
    return (
        f"{seconds // 3600}h {seconds % 3600 // 60:02d}m"
        if seconds >= 3600
        else f"{seconds // 60}m {seconds % 60:02d}s"
    )


def tool_env() -> dict[str, str]:
    return os.environ | {"PATH": f"{os.environ.get('PATH', '')}:{TOOL_PATH}"}


def run(
    *argv: str, cwd: Path | None = None, timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv, cwd=cwd or REPO, env=tool_env(), capture_output=True, text=True, timeout=timeout, check=False
    )


def mini_mode_binary() -> str | None:
    return shutil.which("mini-mode", path=f"{os.environ.get('PATH', '')}:{Path.home() / '.local/bin'}")


def mini_mode(*argv: str, timeout: float = 1800) -> tuple[str, str]:
    """(outcome word, last output line) of a mini-mode command."""
    binary = mini_mode_binary()
    if binary is None:
        return "missing", "mini-mode is not on PATH"
    result = run(binary, *argv, timeout=timeout)
    outcome = MINI_MODE_EXIT.get(result.returncode, f"exit {result.returncode}")
    tail = (result.stderr.strip().splitlines() or result.stdout.strip().splitlines() or [""])[-1]
    for line in result.stdout.splitlines():
        log(f"  {line}")
    for line in result.stderr.splitlines():
        log(f"  {line}")
    return outcome, tail


def notify(message: str, *, title: str = "research-mini: queue", priority: int | None = None) -> None:
    argv = ["notify", "--title", title]
    if priority is not None:
        argv += ["--priority", str(priority)]
    outcome, _ = mini_mode(*argv, message, timeout=60)
    log(f"notify ({outcome}): {message}")


def git(*argv: str) -> subprocess.CompletedProcess[str]:
    return run("git", *argv)


# ---------------------------------------------------------------- specs


def load_spec(path: Path) -> Spec:
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as e:
        raise SpecError(f"{path.name}: not readable YAML: {e}") from e
    if not isinstance(data, dict):
        raise SpecError(f"{path.name}: the spec must be a mapping")
    if not RUN_ID.fullmatch(path.stem):
        raise SpecError(f"{path.name}: the file name (the run id) may hold letters, digits, '.', '_' and '-'")
    minutes = data.get("estimated_minutes")
    if not isinstance(minutes, int) or isinstance(minutes, bool) or minutes <= 0:
        raise SpecError(f"{path.name}: estimated_minutes must be a positive integer")
    inspect = data.get("inspect")
    if not isinstance(inspect, list) or not inspect or not all(isinstance(a, str | int) for a in inspect):
        raise SpecError(f"{path.name}: inspect must be a list of arguments, starting with the subcommand")
    inspect = [str(a) for a in inspect]
    if inspect[0] not in ("eval", "eval-set"):
        raise SpecError(
            f"{path.name}: the first inspect argument must be eval or eval-set, not {inspect[0]!r}"
        )
    if "--log-dir" in inspect:
        raise SpecError(f"{path.name}: do not give --log-dir; the logs of a run go to logs/<run-id>/")
    note = data.get("note")
    if note is not None and not isinstance(note, str):
        raise SpecError(f"{path.name}: note must be text")
    resume = data.get("resume")
    if resume is not None and not isinstance(resume, dict):
        raise SpecError(f"{path.name}: resume must be a mapping (the runner writes it)")
    known = {"estimated_minutes", "inspect", "note", "queued", "resume", "attempts"}
    return Spec(
        path=path,
        estimated_minutes=minutes,
        inspect=inspect,
        note=note,
        queued=data.get("queued"),
        resume=resume,
        attempts=int(data.get("attempts") or 0),
        extra={k: v for k, v in data.items() if k not in known},
    )


def save_spec(spec: Spec, state: str) -> Spec:
    """Write the spec into queue/<state>/ and remove it from where it was."""
    target = QUEUE / state / spec.path.name
    target.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(spec.to_dict(), sort_keys=False, allow_unicode=True)
    target.write_text(text)
    if spec.path != target and spec.path.exists():
        spec.path.unlink()
    spec.path = target
    return spec


def specs_in(state: str) -> list[Spec]:
    """Specs of one state, oldest first (by the `queued` time, then the file time, then the name)."""
    found = []
    for path in (QUEUE / state).glob("*.yaml"):
        try:
            found.append(load_spec(path))
        except SpecError as e:
            log(f"skip: {e}")
    return sorted(
        found,
        key=lambda s: (
            s.queued or dt.datetime.fromtimestamp(s.path.stat().st_mtime).astimezone().isoformat(),
            s.run_id,
        ),
    )


def fits(spec: Spec, deadline: dt.datetime | None, at: dt.datetime) -> bool:
    """A spec starts only when its estimate plus the margin ends before the deadline."""
    if deadline is None:
        return True
    return at + dt.timedelta(minutes=spec.estimated_minutes + MARGIN_MINUTES) <= deadline


def next_spec(deadline: dt.datetime | None, at: dt.datetime) -> tuple[Spec | None, list[Spec]]:
    """The oldest pending spec that fits, and the pending specs that do not fit."""
    skipped = []
    for spec in specs_in("pending"):
        if fits(spec, deadline, at):
            return spec, skipped
        skipped.append(spec)
    return None, skipped


def window_deadline(at: dt.datetime, end: dt.time = WINDOW_END) -> dt.datetime:
    """The next time the local clock shows the window end."""
    deadline = at.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    return deadline if deadline > at else deadline + dt.timedelta(days=1)


def partial_log(run_id: str) -> Path | None:
    """The newest Inspect log of a run, relative to the repository, or None."""
    logs = sorted((REPO / "logs" / run_id).glob("*.eval"), key=lambda p: p.stat().st_mtime)
    return logs[-1].relative_to(REPO) if logs else None


# ---------------------------------------------------------------- the ledger


def ledger_append(record: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with GRADUATION_LOG.open("a") as f:
        f.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------- one run


@dataclass
class Stop:
    """Set once by a signal handler or by the window clock."""

    reason: str | None = None
    event: threading.Event = field(default_factory=threading.Event)

    def request(self, reason: str) -> None:
        if self.reason is None:
            self.reason = reason
            self.event.set()


class Runner:
    def __init__(self, *, deadline: dt.datetime | None, trigger: str, window: bool) -> None:
        self.deadline = deadline
        self.trigger = trigger
        self.window = window
        self.stop = Stop()
        self.child: subprocess.Popen[bytes] | None = None
        signal.signal(signal.SIGUSR1, lambda *_: self.stop.request("preempt"))
        signal.signal(signal.SIGINT, lambda *_: self.stop.request("signal"))
        signal.signal(signal.SIGTERM, lambda *_: self.stop.request("signal"))

    # -- recovery of a killed runner

    def recover(self) -> list[str]:
        """Specs left in running/ go back to pending/ with a resume marker; the box is restored."""
        recovered = []
        for spec in specs_in("running"):
            spec.resume = {
                "log": partial_log(spec.run_id).as_posix() if partial_log(spec.run_id) else None,
                "reason": "killed",
                "at": now().isoformat(timespec="seconds"),
            }
            save_spec(spec, "pending")
            recovered.append(spec.run_id)
            log(f"{spec.run_id}: found in running/ (the runner was killed); requeued with a resume marker")
        if recovered:
            outcome, tail = mini_mode("interactive")
            log(f"restore interactive mode after the kill: {outcome} ({tail})")
            if outcome != "ok":
                notify(f"recovery after a killed runner: mini-mode interactive {outcome}: {tail}", priority=4)
        return recovered

    # -- the steps

    def switch_to_research(self, spec: Spec) -> tuple[str, str]:
        argv = ["research", "--run-id", spec.run_id, "--pid", str(os.getpid())]
        if self.deadline is not None:
            argv += ["--until", self.deadline.isoformat(timespec="seconds")]
        return mini_mode(*argv)

    def run_inspect(self, spec: Spec) -> tuple[int | None, str]:
        """Run tm.run; return (exit code, tail of its output). None = stopped by us."""
        argv = [sys.executable, "-m", "tm.run", "--run-id", spec.run_id]
        if spec.note is not None:
            argv += ["--note", spec.note]
        has_manifest = (REPO / "manifests" / f"{spec.run_id}.json").exists()
        if has_manifest:
            argv.append("--resume")  # an earlier attempt exists; tm.run keeps it under `attempts`
        if spec.resume and spec.resume.get("log") and has_manifest:
            argv += ["--", "eval-retry", spec.resume["log"]]  # the finished samples are kept
        else:
            argv += ["--", *spec.inspect]  # no partial log: the run starts from the beginning
        env = tool_env() | {"INSPECT_DISPLAY": os.environ.get("INSPECT_DISPLAY", "plain")}
        log(f"{spec.run_id}: {' '.join(argv[1:])}")
        tail: collections.deque[str] = collections.deque(maxlen=200)
        self.child = subprocess.Popen(
            argv, cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        assert self.child.stdout is not None

        def copy() -> None:
            for raw in self.child.stdout:  # type: ignore[union-attr]
                line = raw.decode(errors="replace").rstrip("\n")
                tail.append(line)
                print(line, flush=True)

        reader = threading.Thread(target=copy, daemon=True)
        reader.start()
        stopped = False
        while True:
            try:
                code = self.child.wait(timeout=2)
                break
            except subprocess.TimeoutExpired:
                pass
            if self.deadline is not None and now() >= self.deadline:
                self.stop.request("window-end")
            if self.stop.reason is not None and not stopped:
                stopped = True
                log(f"{spec.run_id}: stop ({self.stop.reason}); SIGINT to tm.run, Inspect closes its log")
                self.child.send_signal(signal.SIGINT)
                try:
                    code = self.child.wait(timeout=STOP_GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    log(f"{spec.run_id}: tm.run did not end in {STOP_GRACE_SECONDS} s; SIGTERM")
                    self.child.terminate()
                    try:
                        code = self.child.wait(timeout=60)
                    except subprocess.TimeoutExpired:
                        self.child.kill()
                        code = self.child.wait()
                break
        reader.join(timeout=10)
        self.child = None
        return (None if stopped else code), "\n".join(tail)

    def requeue(self, spec: Spec, reason: str) -> None:
        """The interrupted spec goes back to pending/ with a resume marker; the manifest records it."""
        at = now().isoformat(timespec="seconds")
        spec.resume = {
            "log": (p.as_posix() if (p := partial_log(spec.run_id)) else None),
            "reason": reason,
            "at": at,
        }
        save_spec(spec, "pending")
        manifest_path = REPO / "manifests" / f"{spec.run_id}.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            manifest["interruption"] = {"reason": reason, "at": at, "requeued": True}
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    def commit(self, spec: Spec, message: str) -> tuple[bool, bool]:
        """(committed, pushed) for the manifest of the run and the queue directory."""
        git("add", "--", "queue", f"manifests/{spec.run_id}.json")
        if not git("status", "--porcelain", "--", "queue", f"manifests/{spec.run_id}.json").stdout.strip():
            log(f"{spec.run_id}: nothing to commit")
            committed = True
        else:
            result = git("commit", "-q", "-m", message)
            committed = result.returncode == 0
            if not committed:
                log(f"{spec.run_id}: commit FAILED: {(result.stderr or result.stdout).strip()[-600:]}")
                return False, False
            log(f"{spec.run_id}: committed {git('rev-parse', '--short', 'HEAD').stdout.strip()}")
        pushed = git("push", "-q", "origin", "HEAD:main").returncode == 0
        if not pushed:
            log(f"{spec.run_id}: push FAILED")
        return committed, pushed

    def publish(self, spec: Spec) -> tuple[bool, str]:
        result = run(sys.executable, "-m", "tm.publish", spec.run_id, timeout=3600)
        for line in (result.stdout + result.stderr).splitlines():
            log(f"  {line}")
        manifest = json.loads((REPO / "manifests" / f"{spec.run_id}.json").read_text())
        if manifest.get("status") == "scrub-failed":
            return False, "scrub-failed"
        if result.returncode != 0:
            return False, "publish-failed"
        verified = all(log_.get("published", {}).get("verified") for log_ in manifest.get("logs", []))
        return verified, "verified" if verified else "not-verified"

    # -- one spec, start to end

    def process(self, spec: Spec, *, recovered: bool) -> str:
        """Returns: done, failed, stopped, hold, busy, lease, switch-failed."""
        t0 = time.monotonic()
        outcome, tail = self.switch_to_research(spec)
        if outcome in ("hold", "busy", "lease"):
            log(f"{spec.run_id}: research mode refused ({outcome}): {tail}")
            return outcome
        if outcome != "ok":
            log(f"{spec.run_id}: switch to research mode {outcome}: {tail}")
            notify(f"{spec.run_id}: switch to research mode {outcome}: {tail}", priority=4)
            self.ledger(spec, "unclean", f"switch-{outcome}", {}, recovered)
            return "switch-failed"
        if not spec.queued:
            spec.queued = now().isoformat(timespec="seconds")
        spec.attempts += 1
        save_spec(spec, "running")

        code, tail = self.run_inspect(spec)
        if code is not None and code != 0 and MODEL_LIMIT_TEXT in tail:
            for wait in MODEL_LIMIT_BACKOFF:
                if self.stop.reason is not None:
                    break
                log(f"{spec.run_id}: router said '{MODEL_LIMIT_TEXT}'; retry in {wait} s")
                self.stop.event.wait(wait)
                spec.resume = {
                    "log": (p.as_posix() if (p := partial_log(spec.run_id)) else None),
                    "reason": "model-limit",
                }
                spec.attempts += 1
                save_spec(spec, "running")
                code, tail = self.run_inspect(spec)
                if code == 0 or code is None or MODEL_LIMIT_TEXT not in tail:
                    break

        manifest_path = REPO / "manifests" / f"{spec.run_id}.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        status = manifest.get("status", "no-manifest")
        checks: dict[str, bool] = {}

        if code is None:
            reason = self.stop.reason or "signal"
            self.requeue(spec, reason)
            checks["manifest_committed"], checks["pushed"] = self.commit(
                spec, f"{spec.run_id}: interrupted ({reason}), requeued with a resume marker"
            )
            result = "stopped"
        else:
            if status == "completed":
                checks["logs_verified"], publish_state = self.publish(spec)
                spec.resume = None
                save_spec(spec, "done" if checks["logs_verified"] else "failed")
                result = "done" if checks["logs_verified"] else "failed"
                summary = f"{spec.run_id}: completed, logs {publish_state}"
            else:
                spec.resume = None
                save_spec(spec, "failed")
                result = "failed"
                summary = f"{spec.run_id}: {status} (exit {code})"
            checks["manifest_committed"], checks["pushed"] = self.commit(spec, summary)

        outcome, tail2 = mini_mode("interactive")
        checks["interactive"] = outcome == "ok"
        if outcome != "ok":
            log(f"{spec.run_id}: mini-mode interactive {outcome}: {tail2}")
        elapsed = duration(time.monotonic() - t0)

        if result == "stopped":
            verdict = "preempted"
            text = (
                f"{spec.run_id}: stopped ({self.stop.reason}), requeued; interactive: {checks['interactive']}"
            )
        else:
            clean = result == "done" and all(checks.values())
            verdict = "clean" if clean else "unclean"
            failed_checks = ", ".join(k for k, v in checks.items() if not v)
            text = f"{spec.run_id}: {status}; {result}" + (
                f"; failed: {failed_checks}" if failed_checks else ""
            )
        text += f" ({elapsed}, {self.trigger})"
        self.ledger(
            spec,
            verdict,
            result if result != "stopped" else (self.stop.reason or "signal"),
            checks,
            recovered,
        )
        notify(text, priority=4 if verdict == "unclean" else None)
        return result

    def ledger(self, spec: Spec, verdict: str, reason: str, checks: dict[str, bool], recovered: bool) -> None:
        ledger_append(
            {
                "ts": now().isoformat(timespec="seconds"),
                "run_id": spec.run_id,
                "trigger": self.trigger,
                "outcome": verdict,
                "reason": reason,
                "checks": checks,
                "recovered_from_kill": recovered,
                "attempts": spec.attempts,
            }
        )

    # -- the loop

    def loop(self, *, once: bool) -> int:
        recovered = set(self.recover())
        skipped_reported: set[str] = set()
        if self.window:
            # A hold at the start of the window skips the window and says so.
            status = run(mini_mode_binary() or "mini-mode", "status", "--json")
            try:
                hold = json.loads(status.stdout).get("hold")
            except ValueError:
                hold = None
            if hold:
                reason = hold.get("reason") or "-"
                text = f"window skipped: a hold is active until {hold.get('expires')} (reason: {reason})"
                log(text)
                notify(text)
                return 3
        while self.stop.reason is None:
            at = now()
            if self.deadline is not None and at >= self.deadline:
                log("the window has ended")
                break
            spec, skipped = next_spec(self.deadline, at)
            for s in skipped:
                if s.run_id not in skipped_reported:
                    skipped_reported.add(s.run_id)
                    log(
                        f"{s.run_id}: not started; {s.estimated_minutes} min + {MARGIN_MINUTES} min margin "
                        f"does not fit before {self.deadline:%H:%M}"
                    )
            if spec is None:
                log("no pending spec fits" if skipped else "the queue is empty")
                break
            result = self.process(spec, recovered=spec.run_id in recovered)
            if result == "hold":
                notify(f"queue stopped: a hold is active ({spec.run_id} stays pending)")
                return 3
            if result == "busy":
                if self.deadline is None:
                    log("the interactive router is in use; try again later, or `mini-mode research --force`")
                    return 5
                log(f"the interactive router is in use; next try in {BUSY_RETRY_SECONDS // 60} min")
                self.stop.event.wait(BUSY_RETRY_SECONDS)
                continue
            if result in ("lease", "switch-failed"):
                notify(f"queue stopped: {result} ({spec.run_id} stays pending)", priority=4)
                return 1
            if result == "stopped" or once:
                break
        if self.stop.reason is not None:
            log(f"runner stopped ({self.stop.reason})")
        return 0


# ---------------------------------------------------------------- commands


def cmd_run(args: argparse.Namespace) -> int:
    deadline = None
    trigger = "manual"
    window = False
    if args.window:
        deadline, trigger, window = window_deadline(now()), "window", True
    if args.test_window is not None:
        deadline, trigger, window = now() + dt.timedelta(minutes=args.test_window), "test-window", True
    if args.until:
        deadline = dt.datetime.fromisoformat(args.until)
        if deadline.tzinfo is None:
            deadline = deadline.astimezone()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("another run-queue is running")
            return 1
        log(
            f"start ({trigger}); deadline {deadline.isoformat(timespec='minutes') if deadline else 'none'}; "
            f"pid {os.getpid()}"
        )
        runner = Runner(deadline=deadline, trigger=trigger, window=window)
        return runner.loop(once=args.once)


def cmd_list(args: argparse.Namespace) -> int:
    for state in STATES:
        specs = specs_in(state)
        print(f"{state} ({len(specs)}):")
        for spec in specs:
            marker = f"  resume: {spec.resume.get('reason')}" if spec.resume else ""
            print(f"  {spec.run_id}  {spec.estimated_minutes} min  {' '.join(spec.inspect)}{marker}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    try:
        spec = load_spec(Path(args.spec))
    except SpecError as e:
        print(f"run-queue: {e}", file=sys.stderr)
        return 1
    print(f"{spec.run_id}: ok; {spec.estimated_minutes} min; inspect {' '.join(spec.inspect)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="run-queue", description="Run the queued specs one at a time.")
    sub = parser.add_subparsers(dest="command", required=True)
    p_run = sub.add_parser("run", help="run pending specs")
    p_run.add_argument("--once", action="store_true", help="one spec, then stop")
    p_run.add_argument("--until", help="ISO 8601 deadline for manual runs")
    p_run.add_argument(
        "--window", action="store_true", help=f"the nightly window: deadline {WINDOW_END:%H:%M}"
    )
    p_run.add_argument(
        "--test-window", type=int, metavar="MINUTES", help="a compressed window that ends in MINUTES"
    )
    p_run.set_defaults(func=cmd_run)
    p_list = sub.add_parser("list", help="show the queue")
    p_list.set_defaults(func=cmd_list)
    p_check = sub.add_parser("check", help="validate a spec file")
    p_check.add_argument("spec")
    p_check.set_defaults(func=cmd_check)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
