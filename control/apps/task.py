"""ControlArena APPS setting with the trusted-monitoring micro-protocol, on local models.

Why APPS: of the ControlArena 19.0.0 settings, it is the smallest one whose sandbox works with
networking off. The agent has no tools except `submit`; the submitted code runs in the
container when it is scored. The Bash setting needs egress for its side task, so it is not used.

    python -m tm.run --run-id ID -- eval control/apps/task.py@apps_tm_honest --limit 5
    python -m tm.run --run-id ID -- eval control/apps/task.py@apps_tm_attack --limit 5
    python -m tm.run --run-id ID -- eval control/apps/task.py@apps_generate_honest --limit 10
    python -m tm.run --run-id ID -- eval control/apps/task.py@apps_generate_attack --limit 10

`apps_generate_honest` and `apps_generate_attack` run the untrusted policy alone, with no monitor:
the "generate" phase of the method by itself. One model stays in memory, so these are also the
tasks for throughput measurements. The stored trajectories are scored by a monitor in a second
phase (not built yet; the `apps_tm_*` tasks score live instead).

The pair below is the one decided after the D13.3 capability measurement (20 honest APPS samples
each: Qwen3.8-27B 15 correct, Ministral-3-8B 7, Gemma 4 E4B 13): the 27B is the untrusted model,
Ministral-3-8B the trusted monitor. Gemma 4 E4B is the second monitor for comparison, given with
`-T trusted=openai-api/llama-cpp/gemma-4-e4b`. The D12 substrate tests ran with the 30B as
untrusted and the 27B as trusted; their manifests record that.
"""

from control_arena import EvalMode
from control_arena.eval import ControlEvalConfig, get_control_task
from control_arena.micro_protocol import trusted_monitoring_builder
from control_arena.policy import untrusted_policy_builder
from control_arena.scorers import max_suspicion_scorer
from control_arena.settings.apps.apps_setting import AppsSetting
from inspect_ai import Task, task
from inspect_ai.model import GenerateConfig, Model, get_model
from inspect_ai.util import SandboxEnvironmentSpec

UNTRUSTED = "openai-api/llama-cpp/qwen3.8-27b"
TRUSTED = "openai-api/llama-cpp/ministral-3-8b"
# Set on every request: the server's own defaults are temperature 0.8 and a random seed. The untrusted
# model gets 12288 output tokens: its preset caps the thinking at 8192 (`reasoning-budget`, research
# router; 4096 cut 40 of 100 honest and all attack samples in E1 night 1; 12288 took 960 s per call, past the
# OpenAI SDK's 600 s default request timeout, E2), so the answer always has room after it. Every spec must
# also pass `--timeout 1500 -M client_timeout=1500`: an abandoned request keeps generating on the server and
# slows every later one. Monitors answer short; 4096 is enough.
SAMPLING = GenerateConfig(temperature=0.0, seed=1, max_tokens=4096)
# E3 (2026-10-05): thinking budget 12288 in the router preset needs room for the answer after the
# thinking: 16384 output tokens (E2 used 12288 with budget 8192).
UNTRUSTED_SAMPLING = GenerateConfig(temperature=0.0, seed=1, max_tokens=16384)
# The OpenAI SDK's default read timeout is 600 s. A generation that takes longer is abandoned by the
# client and retried while the server finishes it anyway, and the retries pile up (E2 probes 1 and 2).
# ControlArena ignores `untrusted_config` when it is given a Model, so the models are built here with
# both the sampling config and the client timeout. Inspect's `--timeout` is a retry budget, not this.
# E3: 16384 tokens at about 13 tok/s is about 1260 s; 2000 s keeps the margin (E2: 1500 s for 12288).
CLIENT_TIMEOUT = 2000


def _model(name: str, config: GenerateConfig, client_timeout: int = CLIENT_TIMEOUT) -> Model:
    return get_model(name, config=config, client_timeout=client_timeout)


def _untrusted(name: str, output_tokens: int) -> Model:
    """The untrusted model with `output_tokens` of room and a client timeout in the same proportion.

    E5 (2026-10-09): the thinking-budget comparison uses a second router preset of the same weights with
    `reasoning-budget = 16384`; it needs 20480 output tokens and 2500 s per call. The default stays 16384
    tokens and 2000 s, so every earlier run's setting is unchanged.
    """
    config = GenerateConfig(temperature=0.0, seed=1, max_tokens=output_tokens)
    return _model(name, config, CLIENT_TIMEOUT * output_tokens // UNTRUSTED_SAMPLING.max_tokens)


class HardenedAppsSetting(AppsSetting):
    """APPS with this repository's sandbox policy (see compose.yaml next to this file)."""

    @classmethod
    def get_name(cls) -> str:
        return "apps_hardened"

    def get_sandbox_config(self) -> SandboxEnvironmentSpec:
        # A relative path: Inspect resolves it from the directory of this file, and no absolute
        # path of the machine goes into the log.
        return SandboxEnvironmentSpec(type="docker", config="compose.yaml")


def _task(mode: EvalMode, untrusted: str = UNTRUSTED, trusted: str = TRUSTED) -> Task:
    return get_control_task(
        setting=HardenedAppsSetting(),
        micro_protocol=trusted_monitoring_builder(),
        mode=mode,
        eval_config=ControlEvalConfig(
            untrusted_model=_model(untrusted, UNTRUSTED_SAMPLING),
            trusted_model=_model(trusted, SAMPLING),
        ),
        monitoring_scorers=[max_suspicion_scorer()],
        task_name=f"apps_tm_{mode.value}",
    )


@task
def apps_tm_honest(untrusted: str = UNTRUSTED, trusted: str = TRUSTED) -> Task:
    return _task(EvalMode.HONEST, untrusted, trusted)


@task
def apps_tm_attack(untrusted: str = UNTRUSTED, trusted: str = TRUSTED) -> Task:
    return _task(EvalMode.ATTACK, untrusted, trusted)


def _generate(mode: EvalMode, untrusted: str, output_tokens: int) -> Task:
    """The untrusted policy alone, no monitor: the generate phase of the method (METHOD.md step 1)."""
    return get_control_task(
        setting=HardenedAppsSetting(),
        micro_protocol=untrusted_policy_builder(),
        mode=mode,
        eval_config=ControlEvalConfig(
            untrusted_model=_untrusted(untrusted, output_tokens), trusted_model=_model(TRUSTED, SAMPLING)
        ),
        task_name=f"apps_generate_{mode.value}",
    )


@task
def apps_generate_honest(
    untrusted: str = UNTRUSTED, output_tokens: int = UNTRUSTED_SAMPLING.max_tokens
) -> Task:
    return _generate(EvalMode.HONEST, untrusted, int(output_tokens))


@task
def apps_generate_attack(
    untrusted: str = UNTRUSTED, output_tokens: int = UNTRUSTED_SAMPLING.max_tokens
) -> Task:
    """The attack policy alone: it is told the side task and asked to insert it. No monitor."""
    return _generate(EvalMode.ATTACK, untrusted, int(output_tokens))
