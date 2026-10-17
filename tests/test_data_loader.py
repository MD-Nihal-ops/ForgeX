"""Tests for Stage 4 material and component reference catalogs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.data_loader import (
    COMPONENTS_PATH,
    MATERIALS_PATH,
    CatalogError,
    ComponentRecord,
    EnvelopeMm,
    MaterialRecord,
    get_component,
    get_material,
    load_components,
    load_materials,
)

REQUIRED_MATERIAL_FIELDS = {
    "name",
    "density_kg_m3",
    "yield_strength_mpa",
    "tensile_strength_mpa",
    "cost_per_kg_usd",
    "printability_notes",
    "typical_use_cases",
    "source_note",
}

REQUIRED_COMPONENT_FIELDS = {
    "name",
    "torque_kg_cm",
    "operating_voltage",
    "mass_kg",
    "approximate_cost_usd",
    "dimensions_mm",
    "source_note",
}

EXPECTED_MATERIALS = {"PLA", "PETG", "ABS", "Nylon", "Aluminum 6061"}
EXPECTED_COMPONENTS = {"SG90 servo", "MG996R servo"}


def test_catalog_files_exist():
    assert MATERIALS_PATH.is_file()
    assert COMPONENTS_PATH.is_file()


def test_load_materials_includes_required_records_and_fields():
    records = load_materials()
    names = {row.name for row in records}
    assert EXPECTED_MATERIALS <= names
    assert len(records) == len(names)
    for row in records:
        payload = row.model_dump()
        assert REQUIRED_MATERIAL_FIELDS <= payload.keys()
        assert row.density_kg_m3 > 0
        assert row.yield_strength_mpa > 0
        assert row.tensile_strength_mpa >= row.yield_strength_mpa
        assert "ESTIMATE" in row.source_note.upper()
        assert row.typical_use_cases


def test_load_components_includes_required_records_and_fields():
    records = load_components()
    names = {row.name for row in records}
    assert EXPECTED_COMPONENTS <= names
    assert len(records) == 2
    for row in records:
        payload = row.model_dump()
        assert REQUIRED_COMPONENT_FIELDS <= payload.keys()
        assert isinstance(row.dimensions_mm, EnvelopeMm)
        assert row.torque_kg_cm > 0
        assert row.mass_kg > 0
        assert "ESTIMATE" in row.source_note.upper()
        assert "datasheet" in row.source_note.lower() or "specification" in row.source_note.lower()


def test_get_material_case_insensitive():
    pla = get_material("pla")
    assert isinstance(pla, MaterialRecord)
    assert pla.name == "PLA"
    assert pla.density_kg_m3 == 1240


def test_get_component_by_name():
    sg90 = get_component("SG90 servo")
    assert isinstance(sg90, ComponentRecord)
    assert sg90.approximate_cost_usd == 3
    mg = get_component("mg996r servo")
    assert mg.name == "MG996R servo"


def test_unknown_material_and_component_raise():
    with pytest.raises(CatalogError, match="unknown material"):
        get_material("Unobtanium")
    with pytest.raises(CatalogError, match="unknown component"):
        get_component("HS-322HD")


def test_invalid_materials_json_raises(tmp_path: Path):
    bad = tmp_path / "materials.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(CatalogError, match="invalid JSON"):
        load_materials(bad)


def test_missing_material_field_raises(tmp_path: Path):
    payload = {
        "schema_version": 1,
        "value_class": "reference_estimate",
        "disclaimer": "test",
        "records": [
            {
                "name": "PLA",
                "density_kg_m3": 1240,
                "yield_strength_mpa": 35,
                "tensile_strength_mpa": 50,
                "cost_per_kg_usd": 20,
                "printability_notes": "ok",
                "typical_use_cases": ["test"],
                "source_note": "REFERENCE ESTIMATE for tests.",
            },
            {
                "name": "Broken",
                "density_kg_m3": 1000,
                "yield_strength_mpa": 10,
                "tensile_strength_mpa": 12,
                "cost_per_kg_usd": 1,
                "printability_notes": "ok",
                "typical_use_cases": ["test"],
            },
        ],
    }
    path = tmp_path / "materials.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CatalogError, match="invalid catalog schema"):
        load_materials(path)


def test_source_note_without_estimate_label_rejected(tmp_path: Path):
    payload = {
        "schema_version": 1,
        "value_class": "reference_estimate",
        "disclaimer": "test",
        "records": [
            {
                "name": "PLA",
                "density_kg_m3": 1240,
                "yield_strength_mpa": 35,
                "tensile_strength_mpa": 50,
                "cost_per_kg_usd": 20,
                "printability_notes": "ok",
                "typical_use_cases": ["test"],
                "source_note": "Official datasheet values.",
            }
        ],
    }
    path = tmp_path / "materials.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CatalogError, match="reference estimate"):
        load_materials(path)


def test_missing_catalog_file_raises(tmp_path: Path):
    with pytest.raises(CatalogError, match="not found"):
        load_components(tmp_path / "missing.json")


def test_aluminum_is_not_claimed_as_fdm():
    metal = get_material("Aluminum 6061")
    assert "not fdm" in metal.printability_notes.lower()
