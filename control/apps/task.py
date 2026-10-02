"""ControlArena APPS setting with the trusted-monitoring micro-protocol, on local models.

Why APPS: of the ControlArena 19.0.0 settings, it is the smallest one whose sandbox works with
networking off. The agent has no tools except `submit`; the submitted code runs in the
container when it is scored. The Bash setting needs egress for its side task, so it is not used.

    python -m tm.run --run-id ID -- eval control/apps/task.py@apps_tm_honest --limit 5
    python -m tm.run --run-id ID -- eval control/apps/task.py@apps_tm_attack --limit 5

This file is plumbing. Which model is trusted and which is untrusted is not decided; the pair
below is the one used to test the substrate.
"""

from control_arena import EvalMode
from control_arena.eval import ControlEvalConfig, get_control_task
from control_arena.micro_protocol import trusted_monitoring_builder
from control_arena.scorers import max_suspicion_scorer
from control_arena.settings.apps.apps_setting import AppsSetting
from inspect_ai import Task, task
from inspect_ai.model import GenerateConfig
from inspect_ai.util import SandboxEnvironmentSpec

UNTRUSTED = "openai-api/llama-cpp/qwen3-coder-30b-a3b"
TRUSTED = "openai-api/llama-cpp/qwen3.8-27b"
# Set on every request: the server's own defaults are temperature 0.8 and a random seed.
SAMPLING = GenerateConfig(temperature=0.0, seed=1, max_tokens=4096)


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
            untrusted_model=untrusted,
            trusted_model=trusted,
            untrusted_config=SAMPLING,
            trusted_config=SAMPLING,
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
