"""Smoke test of the substrate: one sample, one bash tool call inside the sandbox.

It checks plumbing, not model quality: the model must call the tool, the call must run in the
container (which reports Linux; the host does not), and the result must come back to the model.
"""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import bash


@task
def smoke() -> Task:
    return Task(
        dataset=[
            Sample(
                input=(
                    "Use the bash tool to run `uname -s` and then `id -un`. "
                    "Reply with the two outputs on one line, separated by a space."
                ),
                target="Linux",
            )
        ],
        solver=[use_tools(bash(timeout=30)), generate()],
        scorer=includes(),
        sandbox="docker",  # uses compose.yaml next to this file
    )
