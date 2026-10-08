"""Tests of the pure parts of the queue runner (no machine, no model)."""

import datetime as dt
from pathlib import Path

import pytest

from tm import queue

LONDON = dt.timezone(dt.timedelta(hours=1))


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


def test_spec_loads_and_round_trips(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "e1-honest.yaml",
        "estimated_minutes: 40\nnote: APPS honest\n"
        "inspect: [eval, control/apps/task.py@apps_tm_honest, --limit, 20]\n",
    )
    spec = queue.load_spec(path)
    assert spec.run_id == "e1-honest"
    assert spec.estimated_minutes == 40
    assert spec.inspect == ["eval", "control/apps/task.py@apps_tm_honest", "--limit", "20"]  # 20 became text
    assert spec.resume is None
    assert spec.to_dict() == {
        "estimated_minutes": 40,
        "note": "APPS honest",
        "inspect": ["eval", "control/apps/task.py@apps_tm_honest", "--limit", "20"],
    }


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("estimated_minutes: 0\ninspect: [eval, x]\n", "positive integer"),
        ("estimated_minutes: ten\ninspect: [eval, x]\n", "positive integer"),
        ("estimated_minutes: 5\n", "list of arguments"),
        ("estimated_minutes: 5\ninspect: [view, x]\n", "eval or eval-set"),
        ("estimated_minutes: 5\ninspect: [eval, x, --log-dir, y]\n", "--log-dir"),
        ("- a\n- b\n", "mapping"),
        ("estimated_minutes: 5\ninspect: [eval, x]\nresume: yes\n", "resume must be a mapping"),
    ],
)
def test_spec_rejects(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(queue.SpecError, match=message):
        queue.load_spec(write(tmp_path, "bad.yaml", text))


def test_spec_rejects_a_bad_run_id(tmp_path: Path) -> None:
    with pytest.raises(queue.SpecError, match="run id"):
        queue.load_spec(write(tmp_path, "has space.yaml", "estimated_minutes: 5\ninspect: [eval, x]\n"))


def test_fits_counts_the_margin(tmp_path: Path) -> None:
    at = dt.datetime(2026, 10, 3, 20, 0, tzinfo=LONDON)
    spec = queue.load_spec(write(tmp_path, "s.yaml", "estimated_minutes: 60\ninspect: [eval, x]\n"))
    assert queue.fits(spec, None, at)  # no deadline: everything fits
    assert queue.fits(spec, at + dt.timedelta(minutes=70), at)  # 60 + 10 margin, exactly
    assert not queue.fits(spec, at + dt.timedelta(minutes=69), at)


def test_window_deadline_is_the_next_end() -> None:
    evening = dt.datetime(2026, 10, 3, 20, 0, tzinfo=LONDON)
    assert queue.window_deadline(evening) == dt.datetime(2026, 10, 4, 6, 30, tzinfo=LONDON)
    early = dt.datetime(2026, 10, 4, 1, 0, tzinfo=LONDON)
    assert queue.window_deadline(early) == dt.datetime(2026, 10, 4, 6, 30, tzinfo=LONDON)
    at_end = dt.datetime(2026, 10, 4, 6, 30, tzinfo=LONDON)
    assert queue.window_deadline(at_end) == dt.datetime(2026, 10, 5, 6, 30, tzinfo=LONDON)


def test_next_spec_takes_the_oldest_that_fits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queue, "QUEUE", tmp_path)
    pending = tmp_path / "pending"
    pending.mkdir()
    write(
        pending, "long.yaml", "estimated_minutes: 300\ninspect: [eval, x]\nqueued: '2026-10-01T10:00+01:00'\n"
    )
    write(
        pending, "short.yaml", "estimated_minutes: 20\ninspect: [eval, y]\nqueued: '2026-10-02T10:00+01:00'\n"
    )
    at = dt.datetime(2026, 10, 3, 5, 0, tzinfo=LONDON)
    spec, skipped = queue.next_spec(at + dt.timedelta(minutes=90), at)
    assert spec is not None and spec.run_id == "short"
    assert [s.run_id for s in skipped] == ["long"]
    spec, skipped = queue.next_spec(None, at)
    assert spec is not None and spec.run_id == "long" and skipped == []


def test_save_spec_moves_and_keeps_the_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queue, "QUEUE", tmp_path)
    (tmp_path / "pending").mkdir()
    path = write(tmp_path / "pending", "r.yaml", "estimated_minutes: 5\ninspect: [eval, x]\n")
    spec = queue.load_spec(path)
    spec.resume = {"log": "logs/r/a.eval", "reason": "preempt", "at": "2026-10-03T21:00:00+01:00"}
    spec.attempts = 2
    queue.save_spec(spec, "running")
    assert not (tmp_path / "pending/r.yaml").exists()
    again = queue.load_spec(tmp_path / "running/r.yaml")
    assert again.resume == spec.resume
    assert again.attempts == 2
    assert again.state == "running"


def test_save_spec_in_place_with_a_relative_path_keeps_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(queue, "QUEUE", tmp_path)
    monkeypatch.chdir(tmp_path.parent)
    (tmp_path / "pending").mkdir()
    write(tmp_path / "pending", "r.yaml", "estimated_minutes: 5\ninspect: [eval, x]\n")
    spec = queue.load_spec(Path(tmp_path.name) / "pending" / "r.yaml")  # relative, as a person types it
    queue.save_spec(spec, "pending")
    assert (tmp_path / "pending/r.yaml").exists()


def test_is_daytime_span() -> None:
    assert queue.is_daytime(dt.datetime(2026, 10, 8, 7, 0, tzinfo=LONDON))
    assert queue.is_daytime(dt.datetime(2026, 10, 8, 19, 59, tzinfo=LONDON))
    assert not queue.is_daytime(dt.datetime(2026, 10, 8, 20, 0, tzinfo=LONDON))
    assert not queue.is_daytime(dt.datetime(2026, 10, 8, 3, 30, tzinfo=LONDON))


def test_research_argv_consumes_the_give_marker_once(tmp_path: Path) -> None:
    marker = tmp_path / "give-now"
    deadline = dt.datetime(2026, 10, 9, 6, 30, tzinfo=LONDON)
    assert queue.research_argv("r1", 42, None, None) == ["research", "--run-id", "r1", "--pid", "42"]
    assert queue.research_argv("r1", 42, deadline, marker)[-2:] == ["--until", "2026-10-09T06:30:00+01:00"]
    marker.touch()
    argv = queue.research_argv("r1", 42, None, marker)
    assert argv[-1] == "--force" and not marker.exists()
    assert "--force" not in queue.research_argv("r1", 42, None, marker)  # consumed


def test_research_argv_ignores_a_stale_give_marker(tmp_path: Path) -> None:
    marker = tmp_path / "give-now"
    marker.touch()
    later = dt.datetime.now().astimezone() + queue.GIVE_TTL + dt.timedelta(minutes=1)
    assert "--force" not in queue.research_argv("r1", 42, None, marker, at=later)
    assert not marker.exists()  # removed either way
