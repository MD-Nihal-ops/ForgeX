"""Requirement extraction and transparent estimates for residential concepts."""

from __future__ import annotations

import math
import re
from typing import Any

from core.data_loader import (
    CatalogError,
    load_components,
    load_materials,
    load_printers,
    load_residential_materials,
    load_robotic_arm_records,
)

NUMBER = r"(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?)"
NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
}
RESIDENTIAL_REQUIRED_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("floor_area_m2", "Floor area (m²)", "What total floor area in square metres should the concept use?"),
    ("room_count", "Room count", "How many rooms should the concept include?"),
    ("bedroom_count", "Bedroom count", "How many bedrooms should it include?"),
    ("footprint_length_m", "Footprint length (m)", "What footprint length should the concept use?"),
    ("footprint_width_m", "Footprint width (m)", "What footprint width should the concept use?"),
    ("wall_height_m", "Wall height (m)", "What wall height should the concept use?"),
    ("wall_thickness_m", "Wall thickness (m)", "What reference wall thickness should be used for the volume estimate?"),
    ("foundation_thickness_m", "Foundation thickness (m)", "What illustrative foundation slab thickness should the concept use?"),
    ("roof_pitch_degrees", "Roof pitch (degrees)", "What gabled roof pitch in degrees should the concept use?"),
    ("material", "Material", "Which listed catalog material should be considered?"),
    ("budget_amount", "Budget", "What budget amount should be recorded?"),
    ("budget_currency", "Budget currency", "Is that budget in USD or EUR?"),
)


def _number(value: str) -> float:
    if "," in value and "." not in value:
        left, right = value.rsplit(",", 1)
        return float(value.replace(",", "")) if len(right) == 3 else float(f"{left}.{right}")
    return float(value.replace(",", ""))


def _count(text: str, label: str) -> int | None:
    match = re.search(
        rf"\b(?P<count>\d+|{'|'.join(NUMBER_WORDS)})\s*[- ]?{label}\b",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    raw = match.group("count").casefold()
    return int(raw) if raw.isdigit() else NUMBER_WORDS[raw]


def extract_residential_inputs(message: str) -> dict[str, Any]:
    """Extract user-stated residential inputs; do not infer unspecified dimensions."""
    text = message.strip()
    extracted: dict[str, Any] = {}

    area_match = re.search(
        rf"\b(?P<area>{NUMBER})\s*(?:m²|m2|sqm|sq\.?\s*m(?:et(?:er|re)s?)?|square\s+met(?:er|re)s?)\b",
        text,
        re.IGNORECASE,
    )
    if area_match:
        extracted["floor_area_m2"] = _number(area_match.group("area"))

    bedrooms = _count(text, r"bedrooms?")
    rooms = _count(text, r"rooms?")
    if bedrooms is not None:
        extracted["bedroom_count"] = bedrooms
    if rooms is not None:
        extracted["room_count"] = rooms

    dimensions = re.search(
        rf"\b(?P<length>{NUMBER})\s*(?:m|met(?:er|re)s?)?\s*[x×]\s*"
        rf"(?P<width>{NUMBER})\s*(?:m|met(?:er|re)s?)\b",
        text,
        re.IGNORECASE,
    )
    if dimensions:
        extracted["footprint_length_m"] = _number(dimensions.group("length"))
        extracted["footprint_width_m"] = _number(dimensions.group("width"))

    for field, labels in (
        ("wall_height_m", r"(?:wall\s+)?height"),
        ("wall_thickness_m", r"wall\s+thickness"),
        ("foundation_thickness_m", r"foundation\s+thickness"),
    ):
        match = re.search(
            rf"\b{labels}\b\D{{0,12}}(?P<value>{NUMBER})\s*(?:m|met(?:er|re)s?)\b",
            text,
            re.IGNORECASE,
        )
        if match:
            extracted[field] = _number(match.group("value"))

    roof = re.search(
        rf"\b(?:roof\s+)?pitch\b\D{{0,12}}(?P<value>{NUMBER})\s*"
        rf"(?:degrees?|deg|\u00b0)",
        text,
        re.IGNORECASE,
    )
    if roof:
        extracted["roof_pitch_degrees"] = _number(roof.group("value"))

    material_match = re.search(
        r"\b(C25\s*/\s*30\s+concrete|C25\s*/\s*30|mortar|PLA|PETG)\b",
        text,
        re.IGNORECASE,
    )
    if material_match:
        material = re.sub(r"\s+", " ", material_match.group(1).strip())
        extracted["material"] = (
            "C25/30 Concrete"
            if material.casefold().startswith("c25")
            else material.title()
            if material.casefold() == "mortar"
            else material.upper()
        )

    budget = re.search(
        rf"(?:budget(?:\s+(?:of|is|up to))?\s*)?(?P<currency>[$€])\s*"
        rf"(?P<amount>{NUMBER})|\bbudget(?:\s+(?:of|is|up to))?\s*"
        rf"(?P<amount_only>{NUMBER})\s*(?P<code>USD|EUR|euros?|dollars?)?",
        text,
        re.IGNORECASE,
    )
    if budget:
        amount = budget.group("amount") or budget.group("amount_only")
        extracted["budget_amount"] = _number(amount)
        currency = budget.group("currency") or budget.group("code")
        if currency:
            folded = currency.casefold()
            extracted["budget_currency"] = "EUR" if currency == "€" or folded.startswith("eur") or folded == "euro" else "USD"
    return extracted


def missing_residential_fields(values: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"name": name, "label": label, "question": question}
        for name, label, question in RESIDENTIAL_REQUIRED_FIELDS
        if values.get(name) is None or values.get(name) == ""
    ]


def validate_residential_inputs(values: dict[str, Any]) -> dict[str, Any]:
    missing = missing_residential_fields(values)
    if missing:
        raise ValueError(
            "Missing required residential inputs: "
            + ", ".join(item["name"] for item in missing)
        )
    clean = dict(values)
    numeric_fields = [
        name
        for name, _, _ in RESIDENTIAL_REQUIRED_FIELDS
        if name not in {"material", "budget_currency"}
    ]
    for name in numeric_fields:
        value = clean[name]
        if isinstance(value, bool) or not isinstance(value, (float, int)):
            raise ValueError(f"{name} must be numeric.")
        if not math.isfinite(float(value)) or float(value) <= 0:
            raise ValueError(f"{name} must be finite and greater than zero.")
    for name in ("room_count", "bedroom_count"):
        if int(clean[name]) != clean[name]:
            raise ValueError(f"{name} must be a whole number.")
        clean[name] = int(clean[name])
    if clean["bedroom_count"] > clean["room_count"]:
        raise ValueError("bedroom_count cannot exceed room_count.")
    if clean["roof_pitch_degrees"] >= 90:
        raise ValueError("roof_pitch_degrees must be less than 90.")
    if clean["budget_currency"] not in {"USD", "EUR"}:
        raise ValueError("budget_currency must be USD or EUR.")
    accepted_materials = {record.name.casefold() for record in load_residential_materials()}
    if str(clean["material"]).casefold() not in accepted_materials:
        raise ValueError(
            "material must match a residential material record in data/materials.json."
        )
    return clean


def residential_catalog_cards(material_name: str) -> dict[str, Any]:
    material_record: dict[str, Any] | None = None
    try:
        material_record = next(
            record.model_dump(mode="json")
            for record in load_residential_materials()
            if record.name.casefold() == material_name.casefold()
        )
    except (CatalogError, StopIteration):
        material_record = None

    printer_records = load_printers()
    arm_records = load_robotic_arm_records()
    components = load_components()
    material = {
        "status": "AVAILABLE" if material_record else "BLOCKED",
        "record": material_record,
        "source": "data/materials.json",
    }
    printer = {
        "status": "AVAILABLE" if printer_records else "BLOCKED",
        "record": printer_records[0] if printer_records else None,
        "source": "data/printers.json",
        "message": (
            None
            if printer_records
            else "No construction 3D printer manufacturer record is present in the local catalog."
        ),
    }
    arm = {
        "status": "AVAILABLE" if arm_records else "BLOCKED",
        "record": arm_records[0] if arm_records else None,
        "source": "data/components.json",
        "message": (
            None
            if arm_records
            else "No robotic-arm extrusion record is present in the local catalog."
        ),
        "unrelated_component_records": len(components),
    }
    return {
        "material": material,
        "printer": printer,
        "robotic_arm": arm,
    }


def calculate_residential_panel(values: dict[str, Any]) -> dict[str, Any]:
    values = validate_residential_inputs(values)
    length = float(values["footprint_length_m"])
    width = float(values["footprint_width_m"])
    wall_height = float(values["wall_height_m"])
    wall_thickness = float(values["wall_thickness_m"])
    foundation_thickness = float(values["foundation_thickness_m"])
    pitch_radians = math.radians(float(values["roof_pitch_degrees"]))
    floor_area = length * width
    wall_area_ring = floor_area - (length - 2 * wall_thickness) * (
        width - 2 * wall_thickness
    )
    wall_volume = max(0.0, wall_area_ring * wall_height)
    roof_rise = width / 2 * math.tan(pitch_radians)
    roof_volume = length * width * roof_rise / 2
    foundation_volume = floor_area * foundation_thickness
    wall_roof_volume = wall_volume + roof_volume
    total_volume = wall_roof_volume + foundation_volume
    cards = residential_catalog_cards(str(values["material"]))
    material_record = cards["material"]["record"] or {}
    density = material_record.get("density_kg_m3")
    unit_cost = material_record.get("cost_per_kg_usd")
    mass = total_volume * float(density) if density is not None else None
    cost_usd = mass * float(unit_cost) if mass is not None and unit_cost is not None else None

    printer_record = cards["printer"]["record"] or {}
    rate = printer_record.get("deposition_rate_cm3_per_hour")
    print_time = total_volume * 1_000_000 / float(rate) if rate else None
    flags = [
        "Flag: Soil bearing capacity unconfirmed.",
        "Flag: Local seismic code not specified.",
        "Flag: Foundation thickness is a user-provided concept input; footing design and soil bearing capacity remain unverified.",
    ]
    if floor_area and not math.isclose(
        floor_area, float(values["floor_area_m2"]), rel_tol=0.02, abs_tol=0.1
    ):
        flags.append(
            "Flag: Entered floor area differs from footprint length × width; calculations use the entered footprint."
        )
    if mass is None:
        flags.append("Flag: Catalog density is unavailable for the selected material; material mass is not calculated.")
    if cost_usd is None:
        flags.append("Flag: Catalog unit cost is unavailable; material cost is not calculated.")
    if print_time is None:
        flags.append("Flag: Machine deposition rate is unavailable; extrusion time is not calculated.")
    if values["budget_currency"] != "USD":
        flags.append("Flag: Catalog prices are USD only; no EUR conversion is available.")

    return {
        "floor_area_m2": floor_area,
        "declared_floor_area_m2": float(values["floor_area_m2"]),
        "room_count": values["room_count"],
        "bedroom_count": values["bedroom_count"],
        "wall_volume_m3": wall_volume,
        "roof_volume_m3": roof_volume,
        "foundation_volume_m3": foundation_volume,
        "total_wall_roof_volume_m3": wall_roof_volume,
        "total_concept_volume_m3": total_volume,
        "material_mass_kg": mass,
        "estimated_material_cost_usd": cost_usd,
        "estimated_print_time_hours": print_time,
        "budget_amount": float(values["budget_amount"]),
        "budget_currency": values["budget_currency"],
        "within_budget": (
            cost_usd <= float(values["budget_amount"])
            if cost_usd is not None and values["budget_currency"] == "USD"
            else None
        ),
        "roof_rise_m": roof_rise,
        "catalog_cards": cards,
        "missing_data_flags": flags,
    }
