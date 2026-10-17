"""Validation and execution helpers for explicitly requested solver jobs."""

from __future__ import annotations

import math
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

STRUCTURAL_LIMITATIONS = [
    "Solver output is raw numerical output; ForgeX has not independently validated it.",
    "The submitted mesh, material model, loads, and supports are user-supplied assumptions.",
    "No certification, code-compliance, or manufacturing-readiness conclusion is provided.",
]
CFD_LIMITATIONS = [
    "Solver output is raw numerical output; ForgeX has not independently validated it.",
    "The submitted mesh, fluid properties, boundary conditions, and solver case are user-supplied.",
    "No certification, code-compliance, or manufacturing-readiness conclusion is provided.",
]
ANALYSIS_DISCLAIMER = (
    "Analysis outputs are preliminary engineering decision support. They are not "
    "certification, code compliance, or a substitute for review by a qualified engineer."
)
_SAFE_FILE_PART = re.compile(r"[A-Za-z0-9_.-]+\Z")
_OPENFOAM_SOLVERS = {
    "buoyantSimpleFoam",
    "icoFoam",
    "interFoam",
    "pimpleFoam",
    "simpleFoam",
}
_MAX_INPUT_FILE_BYTES = 5_000_000
_SOLVER_TIMEOUT_SECONDS = 900
_CALCULIX_VERSION = re.compile(r"CalculiX Version\s+([A-Za-z0-9.+_-]+)", re.IGNORECASE)
_OPENFOAM_VERSION = re.compile(r"OpenFOAM[- ]v?([A-Za-z0-9.+_-]+)", re.IGNORECASE)


def missing_analysis_inputs(analysis_type: str, inputs: dict[str, Any]) -> list[str]:
    """Return exact required input paths for the selected solver family."""
    missing: list[str] = []
    if analysis_type == "structural":
        material = inputs.get("material_properties")
        if not isinstance(material, dict):
            missing.append("material_properties")
        else:
            for field in ("density_kg_m3", "youngs_modulus_mpa", "yield_strength_mpa"):
                value = material.get(field)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (float, int))
                    or not math.isfinite(float(value))
                    or float(value) <= 0
                ):
                    missing.append(f"material_properties.{field}")
            poisson = material.get("poisson_ratio")
            if (
                isinstance(poisson, bool)
                or not isinstance(poisson, (float, int))
                or not math.isfinite(float(poisson))
                or not 0 <= float(poisson) < 0.5
            ):
                missing.append("material_properties.poisson_ratio")
        loads = inputs.get("loads")
        if not isinstance(loads, list) or not loads:
            missing.append("loads")
        else:
            for index, load in enumerate(loads):
                prefix = f"loads.{index}"
                if not isinstance(load, dict):
                    missing.append(prefix)
                    continue
                magnitude = load.get("magnitude_n")
                if (
                    isinstance(magnitude, bool)
                    or not isinstance(magnitude, (float, int))
                    or not math.isfinite(float(magnitude))
                    or float(magnitude) <= 0
                ):
                    missing.append(f"{prefix}.magnitude_n")
                for field in ("direction", "location"):
                    value = load.get(field)
                    if value is None or value == "" or value == [] or value == {}:
                        missing.append(f"{prefix}.{field}")
        supports = inputs.get("supports")
        if not isinstance(supports, list) or not supports:
            missing.append("supports")
        else:
            for index, support in enumerate(supports):
                prefix = f"supports.{index}"
                if not isinstance(support, dict):
                    missing.append(prefix)
                    continue
                for field in ("type", "location"):
                    value = support.get(field)
                    if value is None or value == "" or value == [] or value == {}:
                        missing.append(f"{prefix}.{field}")
        assumptions = inputs.get("mesh_reference_assumptions")
        if not isinstance(assumptions, dict):
            missing.append("mesh_reference_assumptions")
        else:
            element_type = assumptions.get("element_type")
            geometry_source = assumptions.get("geometry_source")
            mesh_size = assumptions.get("mesh_size_mm")
            if not isinstance(element_type, str) or not element_type.strip():
                missing.append("mesh_reference_assumptions.element_type")
            if (
                isinstance(mesh_size, bool)
                or not isinstance(mesh_size, (float, int))
                or not math.isfinite(float(mesh_size))
                or float(mesh_size) <= 0
            ):
                missing.append("mesh_reference_assumptions.mesh_size_mm")
            if not isinstance(geometry_source, str) or not geometry_source.strip():
                missing.append("mesh_reference_assumptions.geometry_source")
        if not isinstance(inputs.get("solver_input"), str) or not inputs["solver_input"].strip():
            missing.append("solver_input")
    elif analysis_type == "cfd":
        for field in ("fluid_domain", "inlet_conditions", "outlet_conditions"):
            if not isinstance(inputs.get(field), dict) or not inputs[field]:
                missing.append(field)
        if not isinstance(inputs.get("boundary_conditions"), list) or not inputs["boundary_conditions"]:
            missing.append("boundary_conditions")
        files = inputs.get("solver_case_inputs")
        if not isinstance(files, dict):
            missing.append("solver_case_inputs")
        else:
            required_files = (
                "system/controlDict",
                "system/fvSchemes",
                "system/fvSolution",
                "constant/polyMesh/points",
                "constant/polyMesh/faces",
                "constant/polyMesh/owner",
                "constant/polyMesh/neighbour",
                "constant/polyMesh/boundary",
                "0/U",
                "0/p",
            )
            missing.extend(
                f"solver_case_inputs.{path}"
                for path in required_files
                if not isinstance(files.get(path), str) or not files[path].strip()
            )
        solver = inputs.get("solver")
        if not isinstance(solver, str) or not solver.strip():
            missing.append("solver")
    else:
        missing.append("analysis_type")
    return missing


def _safe_case_path(root: Path, relative: str) -> Path:
    parts = Path(relative).parts
    if (
        not relative
        or Path(relative).is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
        or any(not _SAFE_FILE_PART.fullmatch(part) for part in parts)
    ):
        raise ValueError(f"Unsafe solver input path: {relative!r}.")
    target = (root / Path(*parts)).resolve()
    if root.resolve() not in target.parents:
        raise ValueError(f"Solver input path escapes analysis directory: {relative!r}.")
    return target


def _write_solver_logs(work_directory: Path, stdout: str, stderr: str) -> list[str]:
    out_path = work_directory / "solver.stdout.txt"
    err_path = work_directory / "solver.stderr.txt"
    out_path.write_text(stdout, encoding="utf-8", errors="replace")
    err_path.write_text(stderr, encoding="utf-8", errors="replace")
    return [str(out_path), str(err_path)]


def _solver_version(output: str, analysis_type: str) -> str | None:
    pattern = _CALCULIX_VERSION if analysis_type == "structural" else _OPENFOAM_VERSION
    match = pattern.search(output)
    return match.group(1) if match else None


def execute_structural_solver(
    inputs: dict[str, Any],
    work_directory: Path,
) -> dict[str, Any]:
    executable = shutil.which("ccx")
    if executable is None:
        return {
            "status": "BLOCKED",
            "solver_name": "CalculiX (ccx)",
            "solver_version": None,
            "artifact_paths": [],
            "stdout": None,
            "stderr": None,
            "message": "CalculiX executable 'ccx' is unavailable; no solver run or result files were created.",
        }

    work_directory.mkdir(parents=True, exist_ok=True)
    deck_path = work_directory / "model.inp"
    deck_path.write_text(str(inputs["solver_input"]), encoding="utf-8")
    try:
        completed = subprocess.run(
            [executable, "-i", "model"],
            cwd=work_directory,
            capture_output=True,
            text=True,
            timeout=_SOLVER_TIMEOUT_SECONDS,
            check=False,
        )
        stdout, stderr = completed.stdout, completed.stderr
        return_code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return_code = -1
        stderr += f"\nCalculiX process exceeded {_SOLVER_TIMEOUT_SECONDS} seconds."
    except OSError as exc:
        return {
            "status": "BLOCKED",
            "solver_name": "CalculiX (ccx)",
            "solver_version": None,
            "artifact_paths": [],
            "stdout": None,
            "stderr": None,
            "message": (
                "CalculiX could not be started; no solver output was captured "
                f"({type(exc).__name__})."
            ),
        }
    log_paths = _write_solver_logs(work_directory, stdout, stderr)
    artifacts = [
        str(path)
        for path in work_directory.rglob("*")
        if path.is_file() and path != deck_path
    ]
    status = "COMPLETED" if return_code == 0 else "FAILED"
    return {
        "status": status,
        "solver_name": "CalculiX (ccx)",
        "solver_version": _solver_version(stdout + "\n" + stderr, "structural"),
        "artifact_paths": artifacts,
        "stdout": stdout,
        "stderr": stderr,
        "message": (
            "CalculiX returned exit code 0; captured raw solver output is available."
            if return_code == 0
            else f"CalculiX returned exit code {return_code}; inspect raw solver output."
        ),
        "log_paths": log_paths,
    }


def execute_cfd_solver(
    inputs: dict[str, Any],
    work_directory: Path,
) -> dict[str, Any]:
    solver = str(inputs["solver"]).strip()
    if solver not in _OPENFOAM_SOLVERS:
        return {
            "status": "BLOCKED",
            "solver_name": solver,
            "solver_version": None,
            "artifact_paths": [],
            "stdout": None,
            "stderr": None,
            "message": (
                "The requested solver is not in ForgeX's supported OpenFOAM solver "
                "allowlist."
            ),
        }
    executable = shutil.which(solver)
    if executable is None:
        return {
            "status": "BLOCKED",
            "solver_name": f"OpenFOAM ({solver})",
            "solver_version": None,
            "artifact_paths": [],
            "stdout": None,
            "stderr": None,
            "message": f"OpenFOAM solver '{solver}' is unavailable; no solver run or result files were created.",
        }

    work_directory.mkdir(parents=True, exist_ok=True)
    files = inputs["solver_case_inputs"]
    for relative, contents in files.items():
        if not isinstance(relative, str) or not isinstance(contents, str):
            return {
                "status": "BLOCKED",
                "solver_name": f"OpenFOAM ({solver})",
                "solver_version": None,
                "artifact_paths": [],
                "stdout": None,
                "stderr": None,
                "message": "OpenFOAM case files must be string paths mapped to text content.",
            }
        target = _safe_case_path(work_directory, relative)
        encoded = contents.encode("utf-8")
        if len(encoded) > _MAX_INPUT_FILE_BYTES:
            return {
                "status": "BLOCKED",
                "solver_name": f"OpenFOAM ({solver})",
                "solver_version": None,
                "artifact_paths": [],
                "stdout": None,
                "stderr": None,
                "message": f"OpenFOAM input file {relative!r} exceeds the size limit.",
            }
    for relative, contents in files.items():
        target = _safe_case_path(work_directory, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")

    try:
        completed = subprocess.run(
            [executable],
            cwd=work_directory,
            capture_output=True,
            text=True,
            timeout=_SOLVER_TIMEOUT_SECONDS,
            check=False,
        )
        stdout, stderr = completed.stdout, completed.stderr
        return_code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return_code = -1
        stderr += f"\nOpenFOAM process exceeded {_SOLVER_TIMEOUT_SECONDS} seconds."
    except OSError as exc:
        return {
            "status": "BLOCKED",
            "solver_name": f"OpenFOAM ({solver})",
            "solver_version": None,
            "artifact_paths": [],
            "stdout": None,
            "stderr": None,
            "message": (
                f"OpenFOAM solver {solver} could not be started; no solver output "
                f"was captured ({type(exc).__name__})."
            ),
        }
    _write_solver_logs(work_directory, stdout, stderr)
    input_paths = {
        _safe_case_path(work_directory, relative)
        for relative in files
    }
    artifacts = [
        str(path)
        for path in work_directory.rglob("*")
        if path.is_file() and path not in input_paths
    ]
    return {
        "status": "COMPLETED" if return_code == 0 else "FAILED",
        "solver_name": f"OpenFOAM ({solver})",
        "solver_version": _solver_version(stdout + "\n" + stderr, "cfd"),
        "artifact_paths": artifacts,
        "stdout": stdout,
        "stderr": stderr,
        "message": (
            f"OpenFOAM solver {solver} returned exit code 0; captured raw solver output is available."
            if return_code == 0
            else f"OpenFOAM solver {solver} returned exit code {return_code}; inspect raw solver output."
        ),
    }
