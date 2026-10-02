"""Where the machine-level files are.

The defaults are relative to the home directory and match the machine these runs are planned
for. Every value can be changed with an environment variable. A manifest never stores one of
these paths: it stores file names and hashes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DATASET = "dang-w/trusted-monitoring-logs"
MODEL_PREFIX = "openai-api/llama-cpp/"


def _path(variable: str, default: str) -> Path:
    return Path(os.environ.get(variable, default)).expanduser()


@dataclass(frozen=True)
class Machine:
    key_file: Path
    presets: Path
    model_checksums: Path
    llama_server: Path
    switch_log: Path
    base_url: str


def machine() -> Machine:
    return Machine(
        key_file=_path("TM_KEY_FILE", "~/.config/llama/research.key"),
        presets=_path("TM_PRESETS", "~/dotfiles/llama/models.research.ini"),
        model_checksums=_path("TM_MODEL_CHECKSUMS", "~/dotfiles/scripts/working-set.sha256"),
        llama_server=_path("TM_LLAMA_SERVER", "~/src/llama.cpp/build/bin/llama-server"),
        switch_log=_path("TM_SWITCH_LOG", "~/.local/state/pail/mini-mode.jsonl"),
        base_url=os.environ.get("LLAMA_CPP_BASE_URL", "http://127.0.0.1:8081/v1"),
    )
