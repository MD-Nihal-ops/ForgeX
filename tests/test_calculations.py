"""Unit tests for deterministic Stage 3 calculations."""

from __future__ import annotations

import math

import pytest

from core.calculations import (
    STANDARD_GRAVITY_M_S2,
    CalculationValidationError,
    calculate_beam_bending_stress,
    calculate_required_grip_force,
    calculate_safety_factor,
    calculate_servo_torque_required,
    check_minimum_wall_thickness,
    compare_design_alternatives,
    estimate_mass,
    estimate_material_cost,
    estimate_print_time,
    validate_units,
)
from core.models import DesignAlternative
from core.requirements import EvidenceStatus, DesignStatus


def test_required_grip_force_matches_closed_form():
    result = calculate_required_grip_force(1.0, 0.5, 2.0)
    expected = 1.0 * STANDARD_GRAVITY_M_S2 * 2.0 / 0.5
    assert result.equation.startswith("GRIP-01")
    assert result.unit == "N"
    assert result.evidence_status is EvidenceStatus.ESTIMATED
    assert result.output_value == pytest.approx(expected)
    assert "g_m_s2" in result.inputs


def test_required_grip_force_rejects_zero_friction():
    with pytest.raises(CalculationValidationError, match="friction_coefficient"):
        calculate_required_grip_force(0.2, 0.0, 1.5)


def test_servo_torque_required():
    result = calculate_servo_torque_required(10.0, 0.05, 1.5)
    assert result.equation.startswith("SRV-01")
    assert result.unit == "N*m"
    assert result.output_value == pytest.approx(0.75)
    assert result.evidence_status is EvidenceStatus.ESTIMATED


def test_servo_torque_rejects_non_positive_lever():
    with pytest.raises(CalculationValidationError, match="lever_arm_m"):
        calculate_servo_torque_required(10.0, 0.0, 1.0)


def test_beam_bending_stress_cantilever_mpa():
    # σ = F L / Z = 10 * 0.1 / 1e-8 = 1e8 Pa = 100 MPa
    result = calculate_beam_bending_stress(10.0, 0.1, 1e-8)
    assert result.equation.startswith("BND-01")
    assert result.unit == "MPa"
    assert result.output_value == pytest.approx(100.0)
    assert result.inputs["stress_pa"] == pytest.approx(1e8)
    assert result.evidence_status is EvidenceStatus.ESTIMATED


def test_safety_factor_is_yield_over_applied():
    result = calculate_safety_factor(60.0, 20.0)
    assert result.equation.startswith("SF-01")
    assert result.output_value == pytest.approx(3.0)
    assert result.unit == "1"
    assert result.inputs["applied_stress_pa"] == pytest.approx(20e6)


def test_safety_factor_rejects_zero_applied_stress():
    with pytest.raises(CalculationValidationError, match="applied_stress_mpa"):
        calculate_safety_factor(40.0, 0.0)


def test_estimate_mass_volume_times_density():
    result = estimate_mass(1e-5, 1270.0)
    assert result.equation.startswith("MAS-01")
    assert result.unit == "kg"
    assert result.output_value == pytest.approx(0.0127)


def test_estimate_material_cost():
    mass = estimate_mass(1e-5, 1270.0).output_value
    cost = estimate_material_cost(mass, 30.0)
    assert cost.equation.startswith("CST-01")
    assert cost.unit == "USD"
    assert cost.output_value == pytest.approx(0.381)


def test_estimate_print_time_uses_si_then_hours():
    result = estimate_print_time(20.0, 10.0)
    assert result.equation.startswith("PRT-01")
    assert result.unit == "h"
    assert result.output_value == pytest.approx(2.0)
    assert result.inputs["volume_m3"] == pytest.approx(20.0 * 1e-6)
    assert result.inputs["time_s"] == pytest.approx(7200.0)


def test_print_time_rejects_zero_speed():
    with pytest.raises(CalculationValidationError, match="print_speed"):
        estimate_print_time(10.0, 0.0)


def test_wall_thickness_pass_and_fail():
    ok = check_minimum_wall_thickness(2.0, 1.5)
    assert ok.output_value == 1.0
    assert ok.evidence_status is EvidenceStatus.VERIFIED
    assert ok.inputs["thickness_m"] == pytest.approx(0.002)

    bad = check_minimum_wall_thickness(1.0, 1.5)
    assert bad.output_value == 0.0
    assert "thinner" in bad.notes.lower()


def test_validate_units_accepts_documented_si_keys():
    result = validate_units({"mass_kg": 0.4, "force_n": 8.0, "length_m": 0.12})
    assert result.output_value == 1.0
    assert result.evidence_status is EvidenceStatus.VERIFIED
    assert result.inputs["units"]["mass_kg"] == "kg"


def test_validate_units_rejects_unknown_and_non_si_names():
    with pytest.raises(CalculationValidationError, match="unknown input"):
        validate_units({"mass_g": 400})
    with pytest.raises(CalculationValidationError, match="finite"):
        validate_units({"mass_kg": math.inf})
    with pytest.raises(CalculationValidationError, match="non-empty mapping"):
        validate_units({})


def test_compare_design_alternatives_picks_higher_safety_factor():
    alts = [
        {
            "id": "ALT-A",
            "estimated_mass_kg": 0.08,
            "estimated_cost_usd": 4.0,
            "estimated_print_time_hours": 3.0,
            "safety_factor": 1.8,
        },
        {
            "id": "ALT-B",
            "estimated_mass_kg": 0.10,
            "estimated_cost_usd": 5.0,
            "estimated_print_time_hours": 4.0,
            "safety_factor": 3.2,
        },
    ]
    result = compare_design_alternatives(alts)
    assert result.equation.startswith("CMP-01")
    assert result.output_value == pytest.approx(1.0)
    assert "ALT-B" in result.notes


def test_compare_design_alternatives_tie_breaks_on_cost_then_mass():
    cheaper = DesignAlternative(
        id="ALT-CHEAP",
        name="Cheap",
        description="Lower cost, same SF.",
        estimated_mass_kg=0.2,
        estimated_cost_usd=3.0,
        estimated_print_time_hours=2.0,
        key_parameters={"safety_factor": 2.0},
        status=DesignStatus.PROPOSED,
    )
    heavier_same_cost = DesignAlternative(
        id="ALT-HEAVY",
        name="Heavy",
        description="Same cost, more mass.",
        estimated_mass_kg=0.4,
        estimated_cost_usd=3.0,
        estimated_print_time_hours=2.0,
        key_parameters={"safety_factor": 2.0},
        status=DesignStatus.PROPOSED,
    )
    result = compare_design_alternatives([heavier_same_cost, cheaper])
    assert result.output_value == pytest.approx(1.0)


def test_compare_requires_two_complete_alternatives():
    with pytest.raises(CalculationValidationError, match="at least two"):
        compare_design_alternatives(
            [{"id": "ONLY", "estimated_mass_kg": 1, "estimated_cost_usd": 1, "estimated_print_time_hours": 1}]
        )
    with pytest.raises(CalculationValidationError, match="estimated_mass_kg"):
        compare_design_alternatives(
            [
                {"id": "A", "estimated_cost_usd": 1, "estimated_print_time_hours": 1},
                {"id": "B", "estimated_mass_kg": 1, "estimated_cost_usd": 1, "estimated_print_time_hours": 1},
            ]
        )


def test_missing_numeric_inputs_raise():
    with pytest.raises(CalculationValidationError, match="mass_kg"):
        calculate_required_grip_force(None, 0.4, 2.0)  # type: ignore[arg-type]
    with pytest.raises(CalculationValidationError, match="volume_m3"):
        estimate_mass(-1.0, 1000.0)
