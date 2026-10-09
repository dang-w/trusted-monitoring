"""Tests of the parts of the manifest writer that need no model server and no Docker."""

from pathlib import Path

import pytest

from tm.machine import Machine
from tm.manifest import (
    model_ids,
    model_record,
    parse_checksums,
    parse_llama_version,
    parse_presets,
    slot_settings,
    switch_log_entries,
    write_manifest,
)

PRESETS = """\
; comment
version = 1

[*]
jinja = true
parallel = 4
kv-unified-per-slot = 32768

[small]
model = /models/tier1/small/small-Q8_0.gguf

[large]
model = /models/tier1/large/large-Q4.gguf
parallel = 2
"""
CHECKSUMS = (
    f"{'a' * 64}  tier1/small/small-Q8_0.gguf\n{'b' * 64} *tier1/other/other.gguf\nnot a checksum line\n"
)


def machine_in(tmp_path: Path) -> Machine:
    return Machine(
        key_file=tmp_path / "key",
        presets=tmp_path / "presets.ini",
        model_checksums=tmp_path / "sums",
        llama_server=tmp_path / "llama-server",
        switch_log=tmp_path / "switch.jsonl",
        base_url="http://127.0.0.1:1/v1",
    )


def test_presets_apply_the_global_section_and_let_a_model_override_it():
    presets = parse_presets(PRESETS)
    assert set(presets) == {"small", "large"}
    assert presets["small"]["parallel"] == "4"
    assert presets["large"]["parallel"] == "2"
    assert slot_settings(presets["small"]) == {
        "parallel": 4,
        "kv_unified_per_slot": 32768,
        "ctx_size": None,
        "n_predict": None,
        "reasoning_budget": None,
    }


def test_checksums_skip_lines_that_are_not_checksums():
    assert parse_checksums(CHECKSUMS) == {
        "tier1/small/small-Q8_0.gguf": "a" * 64,
        "tier1/other/other.gguf": "b" * 64,
    }


def test_model_record_takes_the_sha256_from_the_checksum_list():
    presets, checksums = parse_presets(PRESETS), parse_checksums(CHECKSUMS)
    assert model_record("small", presets, checksums) == {
        "id": "small",
        "file": "small-Q8_0.gguf",
        "sha256": "a" * 64,
    }
    assert model_record("large", presets, checksums)["sha256"] is None
    assert model_record("absent", presets, checksums)["file"] is None


def test_model_ids_come_from_the_main_model_and_the_roles():
    headers = [
        {
            "model": "openai-api/llama-cpp/large",
            "model_roles": {"trusted": {"model": "openai-api/llama-cpp/small"}},
        },
        {"model": "none/none", "model_roles": {}},  # Inspect's placeholder for a roles-only task
    ]
    assert model_ids(headers) == ["large", "small"]


def test_llama_version_line():
    text = "noise\nversion: 0.5.0-dev (build 11189, commit a25c9865f)\nbuilt with AppleClang"
    assert parse_llama_version(text) == {"version": "0.5.0-dev", "build": 11189, "commit": "a25c9865f"}
    assert parse_llama_version("no version here") is None


def test_switch_log_keeps_only_the_records_of_the_run(tmp_path: Path):
    log = tmp_path / "switch.jsonl"
    log.write_text('{"run_id": "r1", "event": "start"}\nnot json\n{"run_id": "r2"}\n{"event": "hold"}\n')
    assert switch_log_entries(log, "r1") == [{"run_id": "r1", "event": "start"}]
    assert switch_log_entries(tmp_path / "absent", "r1") == []


def test_a_manifest_with_the_home_directory_or_the_key_is_refused(tmp_path: Path):
    on = machine_in(tmp_path)
    on.key_file.write_text("sekret-key-value\n")
    with pytest.raises(ValueError, match="home directory"):
        write_manifest({"run_id": "r1", "path": str(Path.home() / "x")}, repo=tmp_path, on=on)
    with pytest.raises(ValueError, match="API key"):
        write_manifest({"run_id": "r1", "leak": "sekret-key-value"}, repo=tmp_path, on=on)
    assert not (tmp_path / "manifests").exists() or not list((tmp_path / "manifests").iterdir())
    path = write_manifest({"run_id": "r1", "status": "completed"}, repo=tmp_path, on=on)
    assert path.read_text().endswith("\n")


def test_scrub_finds_planted_content_and_passes_clean_bytes():
    from tm.scrub import check_bytes

    secrets, hosts = [b"sekret-key-value"], [b"some-other-box"]
    clean = (
        b'{"base_url": "http://127.0.0.1:8081/v1", "task_file": "smoke/task.py", '
        b'"host": "research-mini.local"}'
    )
    assert check_bytes(clean, known_secrets=secrets, denied_hosts=hosts) == []
    planted = (  # planted test strings; the commit hook is told to allow them on these lines
        b"path /Users/someone/research/logs/x.eval and /Users/someone/other/ "  # gitleaks:allow
        b"addr 100.101.102.103 name laptop.local key sekret-key-value box some-other-box"  # gitleaks:allow
    )
    rules = [rule for rule, _ in check_bytes(planted, known_secrets=secrets, denied_hosts=hosts)]
    assert rules.count("home-directory path") == 1  # one finding per distinct match
    assert "tailnet address" in rules
    assert "host name" in rules
    assert "host name (denylist)" in rules
    assert "contents of a local key file" in rules
    details = [detail for _, detail in check_bytes(planted, known_secrets=secrets, denied_hosts=hosts)]
    assert all("sekret" not in detail for detail in details)


def test_scrub_exempts_cgroup_file_names_but_not_hosts():
    from tm.scrub import check_bytes

    listing = (  # a sandbox listing in a scorer's output (e3-gen-attack-3, sample 79)
        b"/sys/fs/cgroup/memory.events.local\\n/sys/fs/cgroup/cpu.stat.local\\n"
        b"/sys/fs/cgroup/hugetlb.1GB.events.local\\n/sys/fs/cgroup/user.slice/pids.events.local"
    )
    assert check_bytes(listing, known_secrets=[], denied_hosts=[]) == []
    still_hosts = {
        b"ssh laptop.local": "laptop.local",
        b"http://events.local/x": "events.local",
        b"/sys/fs/cgroup/laptop.local": "laptop.local",
        b"/etc/events.local": "events.local",
    }
    for text, host in still_hosts.items():
        assert ("host name", host) in check_bytes(text, known_secrets=[], denied_hosts=[]), text
