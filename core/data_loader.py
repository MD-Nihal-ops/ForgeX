"""Load and validate local material and hobby-component reference catalogs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
MATERIALS_PATH = DATA_DIR / "materials.json"
COMPONENTS_PATH = DATA_DIR / "components.json"
PRINTERS_PATH = DATA_DIR / "printers.json"

NonEmptyStr = Annotated[str, Field(min_length=1)]


class CatalogError(ValueError):
    """Missing file, invalid catalog JSON, or unknown record name."""


class _CatalogModel(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        validate_assignment=True,
    )


class EnvelopeMm(_CatalogModel):
    """Approximate bounding box in millimetres (reference estimate)."""

    length: float = Field(..., gt=0)
    width: float = Field(..., gt=0)
    height: float = Field(..., gt=0)


class MaterialRecord(_CatalogModel):
    name: NonEmptyStr
    density_kg_m3: float = Field(..., gt=0)
    yield_strength_mpa: float = Field(..., gt=0)
    tensile_strength_mpa: float = Field(..., gt=0)
    cost_per_kg_usd: float = Field(..., ge=0)
    printability_notes: NonEmptyStr
    typical_use_cases: list[NonEmptyStr] = Field(min_length=1)
    source_note: NonEmptyStr

    @model_validator(mode="after")
    def yield_not_above_tensile(self) -> MaterialRecord:
        if self.yield_strength_mpa > self.tensile_strength_mpa:
            raise ValueError(
                f"{self.name}: yield_strength_mpa ({self.yield_strength_mpa}) "
                f"exceeds tensile_strength_mpa ({self.tensile_strength_mpa})."
            )
        return self

    @model_validator(mode="after")
    def source_note_must_flag_estimate(self) -> MaterialRecord:
        _require_estimate_label(self.source_note, self.name)
        return self


class ComponentRecord(_CatalogModel):
    name: NonEmptyStr
    torque_kg_cm: float = Field(..., gt=0)
    operating_voltage: NonEmptyStr
    mass_kg: float = Field(..., gt=0)
    approximate_cost_usd: float = Field(..., ge=0)
    dimensions_mm: EnvelopeMm
    source_note: NonEmptyStr

    @model_validator(mode="after")
    def source_note_must_flag_estimate(self) -> ComponentRecord:
        _require_estimate_label(self.source_note, self.name)
        return self


class ResidentialMaterialRecord(_CatalogModel):
    """Catalog entry with explicitly optional data for building materials."""

    name: NonEmptyStr
    density_kg_m3: float | None = Field(default=None, gt=0)
    cost_per_kg_usd: float | None = Field(default=None, ge=0)
    characteristic_strength_cylinder_mpa: float | None = Field(default=None, gt=0)
    characteristic_strength_cube_mpa: float | None = Field(default=None, gt=0)
    source_note: NonEmptyStr


class MaterialCatalogFile(_CatalogModel):
    schema_version: int = Field(..., ge=1)
    value_class: NonEmptyStr
    disclaimer: NonEmptyStr
    records: list[MaterialRecord] = Field(min_length=1)
    residential_records: list[ResidentialMaterialRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_names(self) -> MaterialCatalogFile:
        _require_unique_names([row.name for row in self.records], "materials")
        if self.value_class != "reference_estimate":
            raise ValueError("materials catalog value_class must be 'reference_estimate'.")
        return self


class ComponentCatalogFile(_CatalogModel):
    schema_version: int = Field(..., ge=1)
    value_class: NonEmptyStr
    disclaimer: NonEmptyStr
    records: list[ComponentRecord] = Field(min_length=1)
    robotic_arm_records: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_names(self) -> ComponentCatalogFile:
        _require_unique_names([row.name for row in self.records], "components")
        if self.value_class != "reference_estimate":
            raise ValueError("components catalog value_class must be 'reference_estimate'.")
        return self


def _require_estimate_label(source_note: str, record_name: str) -> None:
    text = source_note.upper()
    if "REFERENCE ESTIMATE" not in text and "ESTIMATED" not in text:
        raise ValueError(
            f"{record_name}: source_note must label values as a reference estimate."
        )


def _require_unique_names(names: list[str], catalog: str) -> None:
    folded = [name.casefold() for name in names]
    if len(set(folded)) != len(folded):
        raise ValueError(f"{catalog} catalog contains duplicate names: {names}")


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise CatalogError(f"catalog file not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CatalogError(f"could not read catalog file {path}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise CatalogError(f"invalid JSON in {path}: {exc}") from exc


def _parse_catalog(path: Path, model: type[MaterialCatalogFile] | type[ComponentCatalogFile]):
    payload = _read_json(path)
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise CatalogError(f"invalid catalog schema in {path}: {exc}") from exc


def load_materials(path: Path | None = None) -> list[MaterialRecord]:
    catalog = _parse_catalog(path or MATERIALS_PATH, MaterialCatalogFile)
    return list(catalog.records)


def load_residential_materials(
    path: Path | None = None,
) -> list[ResidentialMaterialRecord]:
    catalog = _parse_catalog(path or MATERIALS_PATH, MaterialCatalogFile)
    conventional = [
        ResidentialMaterialRecord(
            name=record.name,
            density_kg_m3=record.density_kg_m3,
            cost_per_kg_usd=record.cost_per_kg_usd,
            source_note=record.source_note,
        )
        for record in catalog.records
    ]
    return [*conventional, *catalog.residential_records]


def load_components(path: Path | None = None) -> list[ComponentRecord]:
    catalog = _parse_catalog(path or COMPONENTS_PATH, ComponentCatalogFile)
    return list(catalog.records)


def load_printers(path: Path | None = None) -> list[dict[str, Any]]:
    """Read construction-printer records without supplying missing specifications."""
    payload = _read_json(path or PRINTERS_PATH)
    if not isinstance(payload, dict) or payload.get("value_class") != "manufacturer_specification":
        raise CatalogError(
            "printers catalog must be an object with "
            "value_class='manufacturer_specification'."
        )
    records = payload.get("records")
    if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
        raise CatalogError("printers catalog records must be a list of objects.")
    return records


def load_robotic_arm_records(path: Path | None = None) -> list[dict[str, Any]]:
    catalog = _parse_catalog(path or COMPONENTS_PATH, ComponentCatalogFile)
    return list(catalog.robotic_arm_records)


def _lookup(name: str, records: list[Any], kind: str) -> Any:
    if not isinstance(name, str) or not name.strip():
        raise CatalogError(f"{kind} name is required.")
    needle = name.strip().casefold()
    for row in records:
        if row.name.casefold() == needle:
            return row
    available = ", ".join(sorted(row.name for row in records))
    raise CatalogError(f"unknown {kind} {name!r}. Available: {available}.")


def get_material(name: str, path: Path | None = None) -> MaterialRecord:
    return _lookup(name, load_materials(path), "material")


def get_component(name: str, path: Path | None = None) -> ComponentRecord:
    return _lookup(name, load_components(path), "component")
