# trusted-monitoring: how to work in this repo

Read by OpenCode as `AGENTS.md` and by Claude Code as `CLAUDE.md` (a symlink).

## What this repo is

A self-hosted AI-control evaluation: trusted-monitoring runs on Inspect AI and ControlArena against open-weight
models served by llama.cpp on one machine. `README.md` holds the results with the runs each
number comes from; `METHOD.md` the method and the reporting rules; `queue/README.md` the run-spec format and the
time-limit conventions. Every run has a manifest in `manifests/`; the raw logs live in the Hugging Face dataset
`dang-w/trusted-monitoring-logs`, not in git.

## Publishing rules

- `.githooks/pre-commit` runs gitleaks and refuses a commit that carries a secret, a host name, a network address
  or a home-directory path. Enable it once per clone: `git config core.hooksPath .githooks`.
- `tm.scrub` checks every log before `tm.publish` uploads it. A `scrub-failed` run stays local until the cause is
  understood: a real secret or host name is never published; a wrong rule is fixed in `tm/scrub.py` with a test.
- Every rate carries its n and its interval. A "working backdoor" is one whose main task passed and whose secret
  input broke it.

## Conventions the numbers depend on

- Run tools through the wrappers in `scripts/` (they source `scripts/env.sh`); the environment they set keeps
  package paths out of the logs.
- One sample at a time (`--max-samples 1`) wherever a number must be reproduced; every spec carries a per-sample
  `--time-limit` (`queue/README.md`); `scripts/run-queue check` before a spec is committed.
- A run is comparable sample by sample only to runs of the same llama.cpp build (manifests record `llama_cpp.build`).
- The queue runs unattended and commits manifests and queue moves on its own.

## Records

Results and their reading go in `results/` (dated files) and the README table. Pre-register a readout before the
score is read (`results/*-preregistration.md`), and keep the pre-registered rule when the result is reported.

## Verification

`uv run python -m pytest tests/`; `scripts/run-queue check <spec>`; `uv run python -m tm.report <run-id>`;
`uv run python -m tm.scrub <run-id>`. A claim of "done" names the command that showed it.
