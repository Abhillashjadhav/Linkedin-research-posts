"""Discovery tuning for individual launches and accelerated-learning opportunities."""

from __future__ import annotations

from typing import Mapping, Sequence

from . import daily_cli, topic_value

_INSTALLED = False
_ORIGINAL_ROLE = daily_cli._role
_ORIGINAL_TOPIC_ROLE = topic_value._load_role
_ORIGINAL_INVOKE_SELECTOR = topic_value.invoke_selector
_ORIGINAL_PRIORITY_FOR = topic_value.priority_for

ACCELERATED_LEARNING = "ACCELERATED_LEARNING"

SCOUT_GUIDANCE = """

INDIVIDUAL_BUILDER_DISCOVERY:
Actively look for recent launches by individual builders, researchers, engineers,
product managers, and small teams. Do not let large-company announcements crowd
out smaller but inspectable launches simply because the larger brand has more raw
engagement.

Prioritize concrete, public artifacts such as:
- open-source projects and repositories;
- new tools, agents, workflows, and eval frameworks;
- demos and working prototypes;
- experiments with inspectable outputs;
- technical writeups tied to something a practitioner can inspect, test, reproduce,
  or build on.

When an individual/small-team launch is found, preserve in the topic/why-now fields:
who launched it, what was launched, the artifact/repo/demo when public, what is
actually new, why practitioners care now, and what can be learned by inspecting or
testing it. Social momentum may nominate the launch, but factual claims still need
normal primary/reputable verification downstream.

Treat this as an INDIVIDUAL_LAUNCH opportunity when supported by the public source.
"""

TOPIC_VALUE_GUIDANCE = """

ACCELERATED_LEARNING_ROUTE:
ACCELERATED_LEARNING is an accepted reader-value route alongside capability
 discovery, decision change, and immediate utility. Use it when the supplied
 evidence contains a concrete launch/artifact that lets the author inspect, test,
 reproduce, compare, or build on something quickly enough to teach the target
 audience a useful lesson. Do not invent that the author personally tested or used
 an artifact unless supplied evidence proves it. The route is about a credible
 learning opportunity, not fabricated experience.

Individual/small-team launches must not be downgraded merely because they have less
 raw engagement than a major-company announcement. Judge them on inspectability,
 practitioner usefulness, evidence strength, and the authority contribution the
 author can make beyond repeating the launch.
"""


def _role(name: str) -> str:
    text = _ORIGINAL_ROLE(name)
    if name == "scout":
        return text + SCOUT_GUIDANCE
    return text


def _topic_role() -> str:
    return _ORIGINAL_TOPIC_ROLE() + TOPIC_VALUE_GUIDANCE


def _augment_task(task_prompt: str) -> str:
    old = (
        "Accepted reader-value routes are capability discovery, decision change, "
        "and immediate utility."
    )
    new = (
        "Accepted reader-value routes are capability discovery, decision change, "
        "immediate utility, and accelerated learning. Accelerated learning means a "
        "concrete launch or artifact that can be inspected, tested, reproduced, "
        "compared, or built on quickly enough to teach the target audience something useful."
    )
    if old in task_prompt:
        task_prompt = task_prompt.replace(old, new)
    return task_prompt + TOPIC_VALUE_GUIDANCE


def invoke_selector(
    *,
    target_reader: str,
    authority_goal: str,
    evidence: Sequence[Mapping[str, object]],
    count: int,
    candidate_hints: Sequence[Mapping[str, object]] = (),
    invoker=topic_value._default_invoker,
):
    def augmented_invoker(stage, config, role_prompt, task_prompt, schema):
        return invoker(stage, config, role_prompt + TOPIC_VALUE_GUIDANCE, _augment_task(task_prompt), schema)

    return _ORIGINAL_INVOKE_SELECTOR(
        target_reader=target_reader,
        authority_goal=authority_goal,
        evidence=evidence,
        count=count,
        candidate_hints=candidate_hints,
        invoker=augmented_invoker,
    )


def priority_for(candidate: Mapping[str, object]) -> str:
    if candidate.get("status") == "PASS" and candidate.get("reader_value_type") == ACCELERATED_LEARNING:
        return "LEARNING"
    return _ORIGINAL_PRIORITY_FOR(candidate)


def install() -> None:
    """Install discovery-only builder-launch and accelerated-learning guidance."""
    global _INSTALLED
    if _INSTALLED:
        return
    if ACCELERATED_LEARNING not in topic_value.VALUE_TYPES:
        topic_value.VALUE_TYPES = (*topic_value.VALUE_TYPES, ACCELERATED_LEARNING)
    daily_cli._role = _role  # type: ignore[assignment]
    topic_value._load_role = _topic_role  # type: ignore[assignment]
    topic_value.invoke_selector = invoke_selector  # type: ignore[assignment]
    topic_value.priority_for = priority_for  # type: ignore[assignment]
    _INSTALLED = True
