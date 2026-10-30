"""Tests of the task module's attack-prompt selection (no model, no sandbox)."""

import pytest

from control.apps import task


def test_attack_prompt_names_resolve_to_the_shipped_prompts() -> None:
    assert task.attack_prompt_text("attack_policy") == task.policy_prompts["attack_policy"]
    second = task.attack_prompt_text("attack_policy_additional_instructions")
    assert "{side_task_description}" in second and "variable names or comments" in second
    with pytest.raises(ValueError, match="attack_prompt"):
        task.attack_prompt_text("no-such-prompt")


def test_default_attacker_is_built_exactly_as_before() -> None:
    assert task.DEFAULT_ATTACK_PROMPT == "attack_policy"
    default = task._untrusted_policy("attack_policy")
    plain = task.untrusted_policy_builder()
    assert type(default) is type(plain)
    assert getattr(default, "model_dump", None) is None or default.model_dump() == plain.model_dump()
