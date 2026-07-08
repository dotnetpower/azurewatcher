"""Forecast prediction-interval band - false-positive suppression for #8.

A point forecast (`core/detection/forecast.py`) answers "the trend line
crosses the threshold at ETA T". That is necessary but not sufficient to
act: a noisy series with a wide residual spread can cross on the point
estimate yet stay comfortably inside normal variation. This module adds
the missing **uncertainty band** so a forecast is only treated as a
*confident* breach when the interval - not just the center line - still
breaches at a configured confidence level.

Deterministic and explainable: the band widens with (a) the fitted
residual spread (`residual_std`) and (b) how far into the future the
projection reaches (a forecast one second out is tighter than one at the
horizon edge). It uses only the context a :class:`ForecastFinding`
already carries, so it never re-reads the raw series and adds no new
input surface.

This is a **suppressor, never an amplifier**: it can turn a point-estimate
breach into "not confident" (hold in shadow / abstain), but it never
manufactures a breach the point forecast did not already predict.
"""

from __future__ import annotations

from dataclasses import dataclass

from fdai.core.detection.forecast import ForecastFinding

# Common one-sided confidence levels -> z multiplier. A caller states a
# level by name so the intent ("90% sure the band still breaches") is
# legible; unknown levels are rejected rather than silently defaulted.
_Z_BY_LEVEL: dict[str, float] = {
    "0.80": 1.2816,
    "0.90": 1.6449,
    "0.95": 1.9600,
    "0.99": 2.3263,
}


@dataclass(frozen=True, slots=True)
class ForecastBand:
    """The uncertainty interval around a forecast's horizon projection.

    ``lower`` / ``upper`` bracket ``ForecastFinding.projected_at_horizon``
    at the requested confidence. ``confident_breach`` is the actionable
    signal: ``True`` only when the *near* edge of the band (the pessimistic
    edge for the breach direction) still crosses the threshold.
    """

    confidence_level: str
    z: float
    center: float
    lower: float
    upper: float
    half_width: float
    confident_breach: bool
    reason: str


def prediction_band(
    finding: ForecastFinding,
    *,
    confidence_level: str = "0.90",
) -> ForecastBand:
    """Compute the prediction-interval band for ``finding``'s projection.

    Raises :class:`ValueError` for an unknown ``confidence_level`` - the
    set of supported levels is fixed and explicit so a typo cannot degrade
    the gate to a silent default.

    The half-width is ``z * residual_std * growth``, where ``growth``
    scales from ``1.0`` (projecting at the current instant) up as the
    forecast reaches toward the horizon - a conservative, monotonic proxy
    for the way a linear-fit prediction interval fans out with distance.
    """
    z = _Z_BY_LEVEL.get(confidence_level)
    if z is None:
        supported = ", ".join(sorted(_Z_BY_LEVEL))
        raise ValueError(
            f"unsupported confidence_level '{confidence_level}'; "
            f"supported: {supported}"
        )

    horizon = finding.horizon_seconds
    lead = finding.lead_time_seconds
    # growth in [1.0, 2.0]: tightest for an imminent breach, widest for
    # one projected at the far edge of the horizon. Guard a zero horizon.
    if horizon > 0.0:
        lead_fraction = max(0.0, min(1.0, lead / horizon))
    else:
        lead_fraction = 0.0
    growth = 1.0 + lead_fraction

    half_width = z * finding.residual_std * growth
    center = finding.projected_at_horizon
    lower = center - half_width
    upper = center + half_width

    # The breach is confident only if the *pessimistic* edge of the band
    # still crosses. For a rising breach that is the lower edge; for a
    # falling breach, the upper edge.
    if finding.direction == "rising":
        confident = lower >= finding.threshold
        edge = "lower"
    else:  # "falling"
        confident = upper <= finding.threshold
        edge = "upper"

    reason = (
        f"{edge} band edge "
        f"{lower if finding.direction == 'rising' else upper:.4f} vs threshold "
        f"{finding.threshold:.4f} at {confidence_level} confidence "
        f"(half_width={half_width:.4f}, growth={growth:.3f})"
    )
    return ForecastBand(
        confidence_level=confidence_level,
        z=z,
        center=center,
        lower=lower,
        upper=upper,
        half_width=half_width,
        confident_breach=confident,
        reason=reason,
    )


__all__ = ["ForecastBand", "prediction_band"]
