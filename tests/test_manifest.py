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
        {"model": "openai-api/llama-cpp/large", "model_roles": {"trusted": "openai-api/llama-cpp/small"}},
        {"model": "openai-api/llama-cpp/large", "model_roles": {}},
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
