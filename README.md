# trusted-monitoring

**Status: infrastructure in progress. There are no findings yet.**

This repository will hold control evaluations of *trusted monitoring* that run fully on local
models, on one machine. Today it holds the project skeleton, the run tooling and smoke tests of
the plumbing. No experiment has run.

## The question

In trusted monitoring, a weaker model that we trust reads the actions of a stronger model that we
do not trust, and gives each action a suspicion score. The protocol comes from Greenblatt et al.,
[AI Control: Improving Safety Despite Intentional Subversion](https://arxiv.org/abs/2312.06942).

The question here is practical and small in scope:

> With open-weight models that fit on one desktop machine, how many attack trajectories does a
> small trusted monitor catch at a fixed false-positive rate, and how do we know that the
> measurement of the monitor is itself sound?

The planned method is in [METHOD.md](METHOD.md). It is a plan, not a result.

## What is here now

| item | state |
|---|---|
| Dependencies | [Inspect AI](https://inspect.aisi.org.uk/) 0.3.275 and [ControlArena](https://github.com/UKGovernmentBEIS/control-arena) 19.0.0, pinned in `uv.lock` |
| Commit hook | `.githooks/pre-commit` runs [gitleaks](https://github.com/gitleaks/gitleaks) with `.gitleaks.toml` on every staged change |
| Smoke test | `smoke/`: one sample that checks the plumbing only (model, tool call, sandbox, result). It says nothing about monitoring. |
| Sandbox policy | `smoke/compose.yaml`: no network, non-root user, no host mounts, all capabilities dropped |
| Local model wrapper | `scripts/inspect-local` runs Inspect against a local llama.cpp server; the API key is read from a file outside the repository |
| Run wrapper and manifests | `python -m tm.run --run-id ID -- eval …` runs one Inspect command and always writes `manifests/ID.json`; tests in `tests/` |
| ControlArena plumbing | `control/apps/`: the APPS setting with ControlArena's trusted-monitoring micro-protocol and a hardened sandbox config. Honest and attack mode each ran once on 5 samples as a test of the substrate (manifests `d123-apps-honest`, `d123-apps-attack`). These runs are not results. |
| Run report | `python -m tm.report RUN_ID` prints plain counts from the logs of a run |
| Evaluation code | none yet |
| Results | none yet |

## How runs will be recorded

The intent is that no run can be left out afterwards, including smoke tests, failed runs and
abandoned runs:

- Every run commits a manifest to this repository. The manifest records the code version, the
  model files, the sampling parameters and the sha256 of the run's log.
- Raw Inspect logs do not go into git. They will be published as a dataset at
  <https://huggingface.co/datasets/dang-w/trusted-monitoring-logs>. That dataset is empty today.

The manifest part is built (`tm/`, `manifests/`). The publishing of logs is not built yet, so no
log is public yet; each manifest already names the path its log will have in the dataset.

## Environment

The runs are planned for one Apple-silicon Mac mini with 64 GB of memory, with models served by
[llama.cpp](https://github.com/ggml-org/llama.cpp). Tools that the untrusted model calls run in
containers with networking off. The machine-level configuration is not part of this repository.

## Set up a clone

```sh
uv sync
git config core.hooksPath .githooks   # needs gitleaks on PATH
uv run pytest
```

## Licence

MIT. See [LICENSE](LICENSE).
