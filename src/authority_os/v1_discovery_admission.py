"""V1-only discovery admission policy that prevents legacy momentum starvation."""

from __future__ import annotations

from typing import Mapping, Sequence

from . import momentum_surface_parallel as momentum

_INSTALLED = False
_ORIGINAL_ATTACH = momentum.attach_authority_fit

RESCUE_MIN_MOMENTUM = 7
RESCUE_MIN_AUTHORITY_FIT = 22
RESCUE_MIN_PLATFORMS = 2
RESCUE_MIN_OBSERVED_AXES = 4


def _authority_total(candidate: Mapping[str, object]) -> int:
    value = candidate.get("authority_fit")
    if isinstance(value, Mapping) and type(value.get("total")) is int:
        return int(value["total"])
    return 0


def _platform_count(candidate: Mapping[str, object]) -> int:
    platforms = candidate.get("platforms")
    return len(platforms) if isinstance(platforms, list) else 0


def qualifies_for_rescue(candidate: Mapping[str, object]) -> bool:
    total = candidate.get("total")
    return (
        candidate.get("momentum_eligible") is not True
        and type(total) is int
        and int(total) >= RESCUE_MIN_MOMENTUM
        and _authority_total(candidate) >= RESCUE_MIN_AUTHORITY_FIT
        and _platform_count(candidate) >= RESCUE_MIN_PLATFORMS
        and int(candidate.get("observed_axes", 0)) >= RESCUE_MIN_OBSERVED_AXES
    )


def attach_authority_fit(
    candidates: Sequence[Mapping[str, object]],
    scores: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    attached = _ORIGINAL_ATTACH(candidates, scores)
    admitted = 0
    for item in attached:
        if item.get("momentum_eligible") is True:
            item["admission_lane"] = "MOMENTUM"
            admitted += 1
        else:
            item["admission_lane"] = "BELOW_FLOOR"

    if admitted < 3:
        rescue = sorted(
            (item for item in attached if qualifies_for_rescue(item)),
            key=lambda item: (
                -_authority_total(item),
                -(int(item["total"]) if type(item.get("total")) is int else -1),
                str(item.get("topic", "")).casefold(),
            ),
        )
        for item in rescue:
            if admitted >= 3:
                break
            item["momentum_eligible"] = True
            item["admission_lane"] = "AUTHORITY_RESCUE"
            admitted += 1
    return attached


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    momentum.attach_authority_fit = attach_authority_fit  # type: ignore[assignment]
    _INSTALLED = True
