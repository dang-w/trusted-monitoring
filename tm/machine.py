"""Where the machine-level files are.

The defaults are relative to the home directory and match the machine these runs are planned
for. Every value can be changed with an environment variable. A manifest never stores one of
these paths: it stores file names and hashes.
"""

from __future__ import annotations

import os
import plistlib
from dataclasses import dataclass
from pathlib import Path

DATASET = "dang-w/trusted-monitoring-logs"
MODEL_PREFIX = "openai-api/llama-cpp/"
LLAMA_SERVER_FALLBACK = "~/src/llama.cpp/build/bin/llama-server"  # b11189, the default before 14 Oct 2026


def _path(variable: str, default: str) -> Path:
    return Path(os.environ.get(variable, default)).expanduser()


def llama_server_in(plist_text: bytes) -> Path | None:
    """The `llama-server` binary a LaunchAgent plist starts (its first program argument), or None."""
    try:
        args = plistlib.loads(plist_text).get("ProgramArguments") or []
    except (plistlib.InvalidFileException, ValueError, TypeError):
        return None
    return Path(args[0]) if args and str(args[0]).endswith("llama-server") else None


def llama_server_default(research_plist: Path) -> Path:
    """The binary the research router runs, read from its plist, so the manifest records the build in use
    (one build directory per llama.cpp release since 14 Oct 2026); the old fixed path without the plist."""
    try:
        found = llama_server_in(research_plist.read_bytes())
    except OSError:
        found = None
    return found or Path(LLAMA_SERVER_FALLBACK).expanduser()


@dataclass(frozen=True)
class Machine:
    key_file: Path
    presets: Path
    model_checksums: Path
    llama_server: Path
    switch_log: Path
    base_url: str


def machine() -> Machine:
    research_plist = _path("TM_RESEARCH_PLIST", "~/dotfiles/launchd/com.pail.llama-research.plist")
    return Machine(
        key_file=_path("TM_KEY_FILE", "~/.config/llama/research.key"),
        presets=_path("TM_PRESETS", "~/dotfiles/llama/models.research.ini"),
        model_checksums=_path("TM_MODEL_CHECKSUMS", "~/dotfiles/scripts/working-set.sha256"),
        llama_server=_path("TM_LLAMA_SERVER", str(llama_server_default(research_plist))),
        switch_log=_path("TM_SWITCH_LOG", "~/.local/state/pail/mini-mode.jsonl"),
        base_url=os.environ.get("LLAMA_CPP_BASE_URL", "http://127.0.0.1:8081/v1"),
    )
