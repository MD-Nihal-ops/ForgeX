"""Deterministic closed-form engineering calculations for ForgeX (Stage 3).

All numeric results are produced here. Language models must not invent values.
Inputs are validated and converted to SI before arithmetic. Results are
``CalculationResult`` records with equation ids, inputs, units, and evidence
status.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from core.models import CalculationResult, DesignAlternative
from core.requirements import EvidenceStatus

STANDARD_GRAVITY_M_S2 = 9.80665
PA_PER_MPA = 1_000_000.0
M3_PER_CM3 = 1e-6
M_PER_MM = 1e-3
SECONDS_PER_HOUR = 3600.0

# Keys accepted by validate_units, with the unit the caller must use.
EXPECTED_INPUT_UNITS: dict[str, str] = {
    "mass_kg": "kg",
    "friction_coefficient": "1",
    "safety_factor": "1",
    "force_n": "N",
    "lever_arm_m": "m",
    "length_m": "m",
    "section_modulus_m3": "m3",
    "material_yield_strength_mpa": "MPa",
    "applied_stress_mpa": "MPa",
    "volume_m3": "m3",
    "material_density_kg_m3": "kg/m3",
    "cost_per_kg": "USD/kg",
    "volume_cm3": "cm3",
    "print_speed_cm3_per_hour": "cm3/h",
    "thickness_mm": "mm",
    "minimum_thickness_mm": "mm",
}


class CalculationValidationError(ValueError):
    """Invalid or missing calculation input."""


def _as_float(name: str, value: Any) -> float:
    if value is None:
        raise CalculationValidationError(f"{name} is required and cannot be None.")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CalculationValidationError(
            f"{name} must be a real number; got {type(value).__name__}."
        )
    number = float(value)
    if not math.isfinite(number):
        raise CalculationValidationError(f"{name} must be finite; got {value!r}.")
    return number


def _require(name: str, value: Any, *, gt: float | None = None, ge: float | None = None) -> float:
    number = _as_float(name, value)
    if gt is not None and not number > gt:
        raise CalculationValidationError(f"{name} must be > {gt}; got {number}.")
    if ge is not None and not number >= ge:
        raise CalculationValidationError(f"{name} must be >= {ge}; got {number}.")
    return number


def _result(
    *,
    name: str,
    equation: str,
    inputs: dict[str, Any],
    output_value: float,
    unit: str,
    evidence_status: EvidenceStatus,
    notes: str,
) -> CalculationResult:
    return CalculationResult(
        name=name,
        equation=equation,
        inputs=inputs,
        output_value=output_value,
        unit=unit,
        evidence_status=evidence_status,
        notes=notes,
    )


def calculate_required_grip_force(
    mass_kg: float,
    friction_coefficient: float,
    safety_factor: float,
) -> CalculationResult:
    """GRIP-01: F = m * g * n / μ  (clamping force to hold payload weight)."""

    mass = _require("mass_kg", mass_kg, ge=0.0)
    mu = _require("friction_coefficient", friction_coefficient, gt=0.0)
    nsf = _require("safety_factor", safety_factor, ge=1.0)
    force_n = mass * STANDARD_GRAVITY_M_S2 * nsf / mu
    return _result(
        name="required_grip_force",
        equation="GRIP-01: F_N = m_kg * g_m_s2 * n_sf / mu",
        inputs={
            "mass_kg": mass,
            "friction_coefficient": mu,
            "safety_factor": nsf,
            "g_m_s2": STANDARD_GRAVITY_M_S2,
        },
        output_value=force_n,
        unit="N",
        evidence_status=EvidenceStatus.ESTIMATED,
        notes=(
            "Closed-form clamp force assuming Coulomb friction against weight. "
            "Friction coefficient is an assumption, not a test result. Not FEA."
        ),
    )


def calculate_servo_torque_required(
    force_n: float,
    lever_arm_m: float,
    safety_factor: float,
) -> CalculationResult:
    """SRV-01: T = F * a * n  (required actuator torque)."""

    force = _require("force_n", force_n, ge=0.0)
    arm = _require("lever_arm_m", lever_arm_m, gt=0.0)
    nsf = _require("safety_factor", safety_factor, ge=1.0)
    torque_nm = force * arm * nsf
    return _result(
        name="servo_torque_required",
        equation="SRV-01: T_Nm = F_N * a_m * n_sf",
        inputs={
            "force_n": force,
            "lever_arm_m": arm,
            "safety_factor": nsf,
        },
        output_value=torque_nm,
        unit="N*m",
        evidence_status=EvidenceStatus.ESTIMATED,
        notes=(
            "Rigid-lever torque; mechanism efficiency and servo derate are not applied. "
            "Not a catalog stall-torque check (SRV-02 is not computed here)."
        ),
    )


def calculate_beam_bending_stress(
    force_n: float,
    length_m: float,
    section_modulus_m3: float,
) -> CalculationResult:
    """BND-01: σ = F L / Z  (cantilever; result reported in MPa)."""

    force = _require("force_n", force_n, ge=0.0)
    length = _require("length_m", length_m, gt=0.0)
    section = _require("section_modulus_m3", section_modulus_m3, gt=0.0)
    stress_pa = (force * length) / section
    stress_mpa = stress_pa / PA_PER_MPA
    return _result(
        name="beam_bending_stress",
        equation="BND-01: sigma_Pa = F_N * L_m / Z_m3; sigma_MPa = sigma_Pa / 1e6",
        inputs={
            "force_n": force,
            "length_m": length,
            "section_modulus_m3": section,
            "stress_pa": stress_pa,
        },
        output_value=stress_mpa,
        unit="MPa",
        evidence_status=EvidenceStatus.ESTIMATED,
        notes=(
            "Cantilever beam formula σ = M/Z with M = F L. Printed plastic is not a "
            "homogeneous isotropic beam; this is not FEA and not a certification."
        ),
    )


def calculate_safety_factor(
    material_yield_strength_mpa: float,
    applied_stress_mpa: float,
) -> CalculationResult:
    """SF-01: n = σ_allow / σ_applied  (catalog yield vs closed-form stress)."""

    yield_mpa = _require(
        "material_yield_strength_mpa", material_yield_strength_mpa, gt=0.0
    )
    applied_mpa = _require("applied_stress_mpa", applied_stress_mpa, gt=0.0)
    yield_pa = yield_mpa * PA_PER_MPA
    applied_pa = applied_mpa * PA_PER_MPA
    factor = yield_pa / applied_pa
    return _result(
        name="safety_factor",
        equation="SF-01: n = sigma_yield_Pa / sigma_applied_Pa",
        inputs={
            "material_yield_strength_mpa": yield_mpa,
            "applied_stress_mpa": applied_mpa,
            "material_yield_strength_pa": yield_pa,
            "applied_stress_pa": applied_pa,
        },
        output_value=factor,
        unit="1",
        evidence_status=EvidenceStatus.ESTIMATED,
        notes=(
            "Closed-form ratio of caller-supplied yield to applied stress. "
            "Not a tested rating and not a safety certification."
        ),
    )


def estimate_mass(volume_m3: float, material_density_kg_m3: float) -> CalculationResult:
    """MAS-01: m = V * ρ  (solid volume; no infill derate in this function)."""

    volume = _require("volume_m3", volume_m3, ge=0.0)
    density = _require("material_density_kg_m3", material_density_kg_m3, gt=0.0)
    mass = volume * density
    return _result(
        name="estimated_mass",
        equation="MAS-01: m_kg = V_m3 * rho_kg_m3",
        inputs={
            "volume_m3": volume,
            "material_density_kg_m3": density,
        },
        output_value=mass,
        unit="kg",
        evidence_status=EvidenceStatus.ESTIMATED,
        notes=(
            "Solid-volume mass from caller-supplied V and catalog density. "
            "Infill, shells, and bought-item masses are not included."
        ),
    )


def estimate_material_cost(mass_kg: float, cost_per_kg: float) -> CalculationResult:
    """CST-01: C = m * unit_cost  (printed material only)."""

    mass = _require("mass_kg", mass_kg, ge=0.0)
    unit_cost = _require("cost_per_kg", cost_per_kg, ge=0.0)
    cost = mass * unit_cost
    return _result(
        name="estimated_material_cost",
        equation="CST-01: C_USD = m_kg * c_USD_per_kg",
        inputs={"mass_kg": mass, "cost_per_kg": unit_cost},
        output_value=cost,
        unit="USD",
        evidence_status=EvidenceStatus.ESTIMATED,
        notes="Printed-material cost only. Fasteners and servos are not included.",
    )


def estimate_print_time(
    volume_cm3: float,
    print_speed_cm3_per_hour: float,
) -> CalculationResult:
    """PRT-01: t = V / Q  after converting cm³ inputs to SI (m³, m³/s)."""

    volume_cm3_v = _require("volume_cm3", volume_cm3, ge=0.0)
    speed_cm3_h = _require("print_speed_cm3_per_hour", print_speed_cm3_per_hour, gt=0.0)
    volume_m3 = volume_cm3_v * M3_PER_CM3
    speed_m3_s = speed_cm3_h * M3_PER_CM3 / SECONDS_PER_HOUR
    time_s = volume_m3 / speed_m3_s
    time_h = time_s / SECONDS_PER_HOUR
    return _result(
        name="estimated_print_time",
        equation="PRT-01: t_s = V_m3 / Q_m3_s; t_h = t_s / 3600",
        inputs={
            "volume_cm3": volume_cm3_v,
            "print_speed_cm3_per_hour": speed_cm3_h,
            "volume_m3": volume_m3,
            "print_speed_m3_s": speed_m3_s,
            "time_s": time_s,
        },
        output_value=time_h,
        unit="h",
        evidence_status=EvidenceStatus.ESTIMATED,
        notes=(
            "Volumetric FDM heuristic. Ignores travel moves, retractions, and layer times. "
            "Display unit is hours; arithmetic used SI volume and volumetric flow."
        ),
    )


def check_minimum_wall_thickness(
    thickness_mm: float,
    minimum_thickness_mm: float,
) -> CalculationResult:
    """Wall check: convert mm → m, then pass=1 if t >= t_min else 0."""

    thickness = _require("thickness_mm", thickness_mm, ge=0.0)
    minimum = _require("minimum_thickness_mm", minimum_thickness_mm, gt=0.0)
    thickness_m = thickness * M_PER_MM
    minimum_m = minimum * M_PER_MM
    passed = 1.0 if thickness_m + 0.0 >= minimum_m else 0.0
    return _result(
        name="minimum_wall_thickness_check",
        equation="WALL-01: pass = 1 if t_m >= t_min_m else 0",
        inputs={
            "thickness_mm": thickness,
            "minimum_thickness_mm": minimum,
            "thickness_m": thickness_m,
            "minimum_thickness_m": minimum_m,
        },
        output_value=passed,
        unit="1",
        evidence_status=EvidenceStatus.VERIFIED,
        notes=(
            "Deterministic comparison of caller-supplied thicknesses after SI conversion. "
            "Does not inspect CAD or slicer walls."
            if passed == 1.0
            else "Wall is thinner than the stated minimum after converting mm to metres."
        ),
    )


def validate_units(inputs: Mapping[str, Any]) -> CalculationResult:
    """Reject missing/non-numeric values and unknown or non-SI field names."""

    if not isinstance(inputs, Mapping) or not inputs:
        raise CalculationValidationError(
            "validate_units requires a non-empty mapping of named numeric inputs."
        )
    checked: dict[str, float] = {}
    for key, raw in inputs.items():
        if not isinstance(key, str) or not key.strip():
            raise CalculationValidationError("input names must be non-empty strings.")
        if key not in EXPECTED_INPUT_UNITS:
            raise CalculationValidationError(
                f"unknown input '{key}'. Use SI (or documented) names: "
                f"{sorted(EXPECTED_INPUT_UNITS)}."
            )
        checked[key] = _as_float(key, raw)
    return _result(
        name="validate_units",
        equation="UNIT-01: require documented SI field names and finite values",
        inputs={**checked, "units": {k: EXPECTED_INPUT_UNITS[k] for k in checked}},
        output_value=1.0,
        unit="1",
        evidence_status=EvidenceStatus.VERIFIED,
        notes="All listed inputs are finite numbers with documented unit suffixes.",
    )


def _alternative_metrics(item: Any, index: int) -> dict[str, Any]:
    if isinstance(item, DesignAlternative):
        ident = item.id
        mass = item.estimated_mass_kg
        cost = item.estimated_cost_usd
        hours = item.estimated_print_time_hours
        extra_sf = item.key_parameters.get("safety_factor")
    elif isinstance(item, Mapping):
        ident = item.get("id", f"ALT-{index}")
        mass = item.get("estimated_mass_kg", item.get("mass_kg"))
        cost = item.get("estimated_cost_usd", item.get("cost_usd"))
        hours = item.get("estimated_print_time_hours", item.get("print_time_hours"))
        extra_sf = item.get("safety_factor")
    else:
        raise CalculationValidationError(
            f"alternatives[{index}] must be a mapping or DesignAlternative."
        )
    if mass is None or cost is None or hours is None:
        raise CalculationValidationError(
            f"alternatives[{index}] ({ident!r}) requires estimated_mass_kg, "
            "estimated_cost_usd, and estimated_print_time_hours."
        )
    metrics = {
        "id": str(ident),
        "estimated_mass_kg": _require(f"alternatives[{index}].estimated_mass_kg", mass, ge=0.0),
        "estimated_cost_usd": _require(f"alternatives[{index}].estimated_cost_usd", cost, ge=0.0),
        "estimated_print_time_hours": _require(
            f"alternatives[{index}].estimated_print_time_hours", hours, ge=0.0
        ),
    }
    if extra_sf is not None:
        metrics["safety_factor"] = _require(
            f"alternatives[{index}].safety_factor", extra_sf, gt=0.0
        )
    return metrics


def compare_design_alternatives(alternatives: Sequence[Any]) -> CalculationResult:
    """CMP-01: pick the best alternative by safety factor, then cost, mass, time.

    ``output_value`` is the zero-based index of the winner.
    """

    if not isinstance(alternatives, Sequence) or isinstance(alternatives, (str, bytes)):
        raise CalculationValidationError("alternatives must be a non-empty sequence.")
    if len(alternatives) < 2:
        raise CalculationValidationError("compare_design_alternatives needs at least two alternatives.")

    rows = [_alternative_metrics(item, i) for i, item in enumerate(alternatives)]
    ids = [row["id"] for row in rows]
    if len(set(ids)) != len(ids):
        raise CalculationValidationError("alternative ids must be unique.")

    def sort_key(row: dict[str, Any]) -> tuple[float, float, float, float, str]:
        # Higher safety factor first (missing SF treated as 0 so provided SF wins).
        sf = float(row.get("safety_factor", 0.0))
        return (
            -sf,
            row["estimated_cost_usd"],
            row["estimated_mass_kg"],
            row["estimated_print_time_hours"],
            row["id"],
        )

    ranked = sorted(range(len(rows)), key=lambda i: sort_key(rows[i]))
    winner_index = ranked[0]
    return _result(
        name="compare_design_alternatives",
        equation=(
            "CMP-01: rank by (-safety_factor, cost_usd, mass_kg, print_time_h, id)"
        ),
        inputs={"alternatives": rows, "ranking_indices": ranked},
        output_value=float(winner_index),
        unit="1",
        evidence_status=EvidenceStatus.ESTIMATED,
        notes=(
            f"Winner is {rows[winner_index]['id']} at index {winner_index}. "
            "Ranking is a deterministic heuristic, not an optimisation study."
        ),
    )
