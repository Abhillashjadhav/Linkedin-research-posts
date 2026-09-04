"""Probe permanent runtime overlays in a fresh interpreter.

This is a test helper, not a separately collected test module. It mirrors the two
live launcher stacks and reports every module-level callable replaced at each layer.
"""

from __future__ import annotations

import importlib
import inspect
import json
import sys
from collections.abc import Callable, Mapping


def _snapshot() -> dict[str, Callable[..., object]]:
    callables: dict[str, Callable[..., object]] = {}
    for module_name, module in tuple(sys.modules.items()):
        if not module_name.startswith("authority_os") or module is None:
            continue
        for attribute, value in vars(module).items():
            if callable(value):
                callables[f"{module_name}.{attribute}"] = value
    return callables


def _compatibility_errors(
    original: Callable[..., object],
    replacement: Callable[..., object],
) -> list[str]:
    try:
        original_parameters = inspect.signature(original).parameters
        replacement_parameters = inspect.signature(replacement).parameters
    except (TypeError, ValueError):
        return []

    replacement_var_positional = any(
        parameter.kind == inspect.Parameter.VAR_POSITIONAL
        for parameter in replacement_parameters.values()
    )
    replacement_var_keyword = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in replacement_parameters.values()
    )
    errors: list[str] = []
    for name, original_parameter in original_parameters.items():
        replacement_parameter = replacement_parameters.get(name)
        if original_parameter.kind == inspect.Parameter.VAR_POSITIONAL:
            if not replacement_var_positional:
                errors.append(f"lost *{name}")
            continue
        if original_parameter.kind == inspect.Parameter.VAR_KEYWORD:
            if not replacement_var_keyword:
                errors.append(f"lost **{name}")
            continue
        if original_parameter.kind == inspect.Parameter.POSITIONAL_ONLY:
            compatible_kind = bool(
                replacement_parameter is not None
                and replacement_parameter.kind == inspect.Parameter.POSITIONAL_ONLY
            ) or replacement_var_positional
        elif original_parameter.kind == inspect.Parameter.KEYWORD_ONLY:
            compatible_kind = bool(
                replacement_parameter is not None
                and replacement_parameter.kind == inspect.Parameter.KEYWORD_ONLY
            )
        else:
            compatible_kind = bool(
                replacement_parameter is not None
                and replacement_parameter.kind
                == inspect.Parameter.POSITIONAL_OR_KEYWORD
            ) or (replacement_var_positional and replacement_var_keyword)
        if not compatible_kind:
            errors.append(f"lost {original_parameter.kind.name.lower()} {name}")
        if (
            original_parameter.default is not inspect.Parameter.empty
            and replacement_parameter is not None
            and replacement_parameter.default is inspect.Parameter.empty
        ):
            errors.append(f"optional parameter {name} became required")

    for name, replacement_parameter in replacement_parameters.items():
        if name in original_parameters or replacement_parameter.kind in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            continue
        if replacement_parameter.default is inspect.Parameter.empty:
            errors.append(f"replacement added required parameter {name}")
    return errors


def _changes(
    before: Mapping[str, Callable[..., object]],
    after: Mapping[str, Callable[..., object]],
) -> tuple[list[str], list[dict[str, object]]]:
    names: list[str] = []
    failures: list[dict[str, object]] = []
    for name, replacement in after.items():
        original = before.get(name)
        if original is None or original is replacement:
            continue
        names.append(name)
        errors = _compatibility_errors(original, replacement)
        if errors:
            failures.append(
                {
                    "target": name,
                    "original": str(inspect.signature(original)),
                    "replacement": str(inspect.signature(replacement)),
                    "errors": errors,
                }
            )
    return sorted(names), failures


def _install(module_name: str) -> tuple[list[str], list[dict[str, object]]]:
    module = importlib.import_module(f"authority_os.{module_name}")
    before = _snapshot()
    preferred_before = None
    if module_name == "v1_runtime_tuning":
        from authority_os import campaign

        preferred_before = campaign.StageModels.preferred
    module.install()
    after = _snapshot()
    names, failures = _changes(before, after)
    if preferred_before is not None:
        from authority_os import campaign

        preferred_after = campaign.StageModels.preferred
        target = "authority_os.campaign.StageModels.preferred"
        names.append(target)
        errors = _compatibility_errors(preferred_before, preferred_after)
        if errors:
            failures.append(
                {
                    "target": target,
                    "original": str(inspect.signature(preferred_before)),
                    "replacement": str(inspect.signature(preferred_after)),
                    "errors": errors,
                }
            )
    return sorted(names), failures


def _record_install(report: dict[str, object], module_name: str) -> None:
    names, failures = _install(module_name)
    report["layers"][module_name] = names  # type: ignore[index]
    report["failures"].extend(failures)  # type: ignore[union-attr]


def _base_stack(report: dict[str, object]) -> None:
    _record_install(report, "v1_gates")
    # Import only after the first V1 layer, matching bin/linkedin-os.
    _record_install(report, "v1_completion")
    _record_install(report, "topic_value_id_contract")


def _discovery_stack(report: dict[str, object]) -> None:
    _base_stack(report)
    for module_name in (
        "daily_spine_cli",
        "daily_cli",
        "momentum_batched",
        "momentum_surface_parallel",
        "topic_value",
        "resonance",
    ):
        importlib.import_module(f"authority_os.{module_name}")
    before = _snapshot()
    daily = importlib.import_module("authority_os.daily_discovery_cli")
    after = _snapshot()
    names, failures = _changes(before, after)
    report["layers"]["daily_discovery_cli"] = names  # type: ignore[index]
    report["failures"].extend(failures)  # type: ignore[union-attr]
    from authority_os import daily_spine_cli

    report["dispatch_ok"] = daily_spine_cli.command is daily.command


def _draft_stack(report: dict[str, object]) -> None:
    _base_stack(report)
    for module_name in (
        "v1_length_policy",
        "single_topic_codex",
        "human_readability",
        "critic_anchor_retry",
        "actionable_diagnostics",
        "social_media_gate_policy",
        "v1_consumability",
        "v1_runtime_tuning",
        "quality_optimizer",
    ):
        _record_install(report, module_name)
    before = _snapshot()
    integrated = importlib.import_module("authority_os.integrated_cli")
    after = _snapshot()
    names, failures = _changes(before, after)
    report["layers"]["integrated_cli"] = names  # type: ignore[index]
    report["failures"].extend(failures)  # type: ignore[union-attr]
    from authority_os import quality_cli, quality_optimizer

    quality_optimizer.wire_integrated_dispatch(integrated)
    report["dispatch_ok"] = (
        quality_cli.COMMANDS["draft"] is quality_cli.command_draft
        and quality_cli.command_draft is integrated._command_draft
    )


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) == 2 else ""
    report: dict[str, object] = {
        "mode": mode,
        "layers": {},
        "failures": [],
        "dispatch_ok": False,
    }
    if mode == "discovery":
        _discovery_stack(report)
    elif mode == "draft":
        _draft_stack(report)
    else:
        raise SystemExit("usage: runtime_overlay_probe.py discovery|draft")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
