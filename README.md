# ForgeX — Imagine it. Engineer it. Build it.

**Team:** `404_Brain_not_F̶o̶u̶n̶d̶`  
**Event:** IBM Z Datathon 2026  
**Event code:** `SSF2026`

ForgeX is a generative engineering platform that turns plain-language requests into
preliminary residential concept designs and traceable engineering decision support.
It helps people explore early ideas; it does not produce certified or
construction-ready designs.

## Problem statement

Early-stage residential design can be slow and costly. Even an initial concept may
require coordination among multiple specialists before a team can compare a layout,
materials, and a rough budget. That makes it harder for people to explore options
early and understand which important project inputs are still unknown.

## Solution

ForgeX accepts a plain-language request and helps users explore a preliminary
residential concept workflow. Depending on the available inputs and catalog records,
it can:

- Route a request to a house concept and review economy, comfort, or premium reference
  tiers.
- Summarize catalog-backed material quantities and estimated material cost, and
  compare an indicative tier cost with a user-provided budget when available.
- Flag missing or unconfirmed engineering information, such as soil bearing capacity
  or local seismic requirements.
- Display a parametric 3D reference model and multiple views for supported house
  concepts.

These are illustrative estimates and concepts, not verified project designs or
construction quotes.

## Tech stack

- **Application and API:** Python, FastAPI, Uvicorn, Pydantic, SciPy
- **Current engineering calculations:** deterministic Python workflows and catalog
  data
- **ML demonstration:** scikit-learn Random Forest, pandas, NumPy, and joblib in
  `ForgeX_Datathon.ipynb`
- **Web views:** Three.js for the interactive viewer; HTML, CSS, and JavaScript for
  the web workbench
- **Notebook environment:** JupyterLab
- **Additional project UI:** Streamlit
- **Packaging and optional capabilities:** Docker; CadQuery and LLM API integrations
  are optional

The Random Forest notebook is an educational surrogate trained on examples derived
from ForgeX reference catalogs and templates. The application API does not currently
load or serve that model; deterministic calculations remain the source of truth.

## IBM Z Datathon platform: LinuxONE (s390x)

IBM LinuxONE is the target platform for this Datathon project. The repository includes
Docker packaging and a LinuxONE deployment checklist to support a deployment to an
`s390x` VM. However, no LinuxONE deployment or execution has been verified for this
submission. In particular, the notebook's Random Forest has been trained and
evaluated in the local development environment; it is **not currently claimed to be
trained or served on LinuxONE**. The FastAPI application currently serves the
deterministic workflows and does not serve the exported notebook model.

## Project structure

- `api/` — FastAPI application, routes, request/response schemas, and persistence
- `src/forgex/` — domain models and calculation modules
- `core/` — application workflows, product registry, calculations, and reports
- `frontend/` and `pages/` — Streamlit application
- `frontend_web/` — standalone web workbench, viewer, and house reference models
- `data/` — material, component, printer, servo, and design-template catalogs
- `ForgeX_Datathon.ipynb` — derived-data ML training and evaluation demonstration
- `scripts/` — local and LinuxONE run guides and capability checks
- `tests/` — project test suite

The Streamlit app includes a conversational, offline Engineering Brief workflow. Its
reusable extraction, clarification, missing-input, and confirmation logic lives in
`core/brief_workflow.py`, independently of the UI. It extracts only user-stated
engineering values, asks follow-up questions in chat, then presents a compact review
form and saves the confirmed brief in the current Streamlit session.

## Supported product families

- Servo-driven gripper: existing three calculation-backed reference alternatives.
- Electronics enclosure: three enclosure concepts with volume, mass, cost, print-time,
  wall, port-clearance, and lid-fit screens.
- Mounting bracket: three bracket concepts with load, bending, safety-factor, mass,
  cost, print-time, and fastener-clearance screens.
- Simple house model: three scale-model concepts with wall/roof estimates and opening
  checks. Not architectural, structural, code-compliant, or construction-ready.
- Residential building concept: parses floor area, room counts, footprint, wall and
  roof inputs; returns reference volume estimates and catalog cards. Soil, seismic,
  local-code, and foundation adequacy remain unverified.
- Civil concept assistant: advisory discussion topics only; no calculations, member
  sizes, construction drawings, or safety approvals.

All non-gripper dimensions and calculations are preliminary reference estimates.
Statuses and evidence are explicit; ForgeX does not claim simulation, certification,
or manufacturing readiness.

The residential concept reads materials from `data/materials.json` and equipment
records from `data/printers.json` and `data/components.json`. The current local printer
and robotic-arm equipment catalogs are empty; consequently deposition time and
manufacturer machine specifications are shown as unavailable. Material density and
cost are only calculated when the selected catalog record supplies those values.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
# Optional: copy .env.example to .env for local configuration.
python -m streamlit run frontend/app.py
```

The Engineering Brief demo does not require an API key and does not send user input to
an external model. Open **1 · Brief** in the Streamlit navigation, describe a
servo-driven gripper or simple structural bracket, answer the agent's follow-up
questions in chat, review the pre-filled confirmation form, and confirm the brief.
The confirmed structured brief remains available in session state until the Streamlit
session ends.

## Jupyter notebook: train and evaluate the demo model

The project-root notebook uses `data/materials.json` and the volume-bearing JSON
templates in `data/design_templates/`. There is no measured CSV training dataset:
the notebook derives example labels with ForgeX's deterministic mass and material
cost equations. Its test metrics therefore demonstrate the training workflow only,
not validated production prediction performance.

Install the development and notebook dependencies, then launch JupyterLab:

```bash
pip install -r requirements.txt -r requirements-dev.txt jupyterlab
jupyter lab ForgeX_Datathon.ipynb
```

In JupyterLab, select **Run → Run All Cells**. The notebook reports separate
held-out R² and MAE values for `estimated_mass_kg` and `estimated_cost_usd`, and
exports `forgex_model.joblib` to the project root. The saved model is not currently
loaded by the API or used by the application calculations.

## FastAPI web workbench

Run the FastAPI backend as described below and open `http://127.0.0.1:8000/app/`.
The shared web workbench has **Design Studio**, **3D Viewer**, and **Wireframe** tabs.
The Design Studio and viewer preserve their standalone pages in isolated frames:
`frontend_web/studio.html` and `frontend_web/try.html`; the Wireframe tab loads the
house reference model. The interactive viewer loads Three.js, OrbitControls,
Chart.js, Tailwind, and Phosphor Icons from public CDNs, so those features require
network access.

The supplied 3D Viewer is a separate concept/demo page and is not connected to the
ForgeX API's engineering calculations or export endpoints. Its current
`exportActiveSTL()` action only shows a notification; it does not generate or download
a real STL file. Use the API-backed Design Studio/export workflow for actual
ForgeX-generated artifacts.

## FastAPI backend

Install runtime dependencies with `pip install -r requirements.txt`, then run:

```bash
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

Interactive API documentation is available at `http://127.0.0.1:8000/docs`. By
default, sessions use in-memory storage and are cleared when the API restarts.

### Optional PostgreSQL persistence

Install dependencies from `requirements.txt`, create an empty PostgreSQL database, and
set these environment variables before running the API. Do not commit credentials:

```powershell
$env:FORGEX_USE_DATABASE = "true"
$env:DATABASE_URL = "postgresql+asyncpg://forgex_user:your-password@127.0.0.1:5432/forgex"
python -m api.init_db
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

`api.init_db` initializes the MVP schema using SQLAlchemy `metadata.create_all`.
When database configuration or connectivity is unavailable, the service logs a
credential-free warning and falls back to process-local memory; that fallback does
not survive restarts. `DATABASE_URL` also accepts the common `postgres://` and
`postgresql://` prefixes, which are adapted to asyncpg. Tests can override the async
database dependency with isolated SQLite.

After confirming a brief and calling `POST /api/design/generate`, generated
alternatives can be exported with:

- `POST /api/design/{design_id}/cad` with `{"session_id":"..."}` to request an STL.
  CadQuery is optional; if it is unavailable or export fails, the endpoint returns
  `BLOCKED` and no artifact path.
- `POST /api/design/{design_id}/report` with `{"session_id":"..."}` to create a
  Markdown engineering report.
- `GET /api/design/{design_id}/report?session_id=...` to retrieve a report that was
  actually created.

Created artifacts are stored under `exports/{session_id}/`. CAD exports are labeled
reference concept models and are not optimized or validated geometry. Reports include
the confirmed brief, assumptions, reference alternatives, recorded calculations and
evidence, a catalog-based reference BOM/material summary, and physical validation
requirements. No export endpoint claims simulation, certification, or manufacturing
readiness.

CadQuery remains optional and is not installed by `requirements.txt`; install it
separately in a CadQuery-compatible Python environment to enable STL generation.

### STL visualization and PNG previews

Install the optional headless preview renderer in the API environment with
`pip install -r requirements-preview.txt`. After successfully creating an STL, call
`POST /api/design/{design_id}/preview` with `{"session_id":"..."}` to render an
isometric PNG from the actual mesh. The endpoint returns `BLOCKED` without an artifact
path if the STL or optional renderer is unavailable.

Install the interactive Streamlit viewer with
`pip install -r frontend/requirements.txt`. On the Export Package screen, create an
STL, then generate its PNG preview. The PNG and rotatable STL viewer appear only when
the API returned artifact paths and the corresponding non-empty files are accessible
to the Streamlit process. Auto-rotation is optional.

### Optional CalculiX / OpenFOAM analysis

Solver analysis is a separate, explicit opt-in workflow; design generation never runs
a solver. In the UI's Export Package analysis tabs, select **Structural analysis** or
**CFD analysis**, provide solver-ready JSON inputs, create the job, review its input
snapshot and limitations, then explicitly click **Run Solver**. Choose **No analysis**
to leave simulation out of the workflow.

The structural API requires user-supplied material properties, loads, supports, mesh
and geometry assumptions, and a CalculiX input deck. The CFD API requires a fluid
domain, boundary and inlet/outlet conditions, an allowlisted OpenFOAM solver name,
and the OpenFOAM case files including mesh and `0/U` / `0/p`. ForgeX does not create
the solver deck, mesh, boundary conditions, or CFD case. Jobs with missing inputs
return `BLOCKED`; if the requested solver executable is unavailable, `/run` returns
`BLOCKED` without result files.

API workflow:

1. `POST /api/analysis/create` with `session_id`, a generated `design_id`,
   `analysis_type` (`structural` or `cfd`), and its explicit `inputs`.
2. Review `GET /api/analysis/{analysis_id}` and explicitly invoke
   `POST /api/analysis/{analysis_id}/run`.
3. Retrieve solver output and actual result artifact paths with
   `GET /api/analysis/{analysis_id}/results`.

Solver processes have a 15-minute timeout. stdout/stderr and solver result files are
stored only after a real process invocation. ForgeX returns raw solver output and does
not calculate or infer stresses, displacements, flow rates, or safety conclusions
from it. Analysis outputs are preliminary engineering decision support. They are not
certification, code compliance, or a substitute for review by a qualified engineer.

### Product family API workflow

For non-gripper product families, send `product_type` and any known `product_inputs`
to `POST /api/brief/start`. The API returns missing fields; provide remaining values
to `POST /api/brief/clarify`, then review and confirm with
`POST /api/brief/confirm`. `POST /api/design/generate` returns family-specific
alternatives, calculation rows, evidence rows, and comparisons. The Streamlit app
offers a product-family selector and corresponding input controls; its existing
gripper conversation remains available unchanged.

Example API families: `electronics_enclosure`, `mounting_bracket`,
`simple_house_model`, and `civil_concept_assistant`.

## Docker packaging

### Local Docker testing

Install and start Docker Desktop with the Docker Compose plugin. From the ForgeX
project root, create a private `.env` file and set a unique, URL-safe PostgreSQL
password. Do not commit `.env`:

```powershell
Copy-Item .env.example .env
# Edit .env and set POSTGRES_PASSWORD to a private value.
docker compose config --quiet
docker compose up --build
```

Open the workbench at `http://localhost:8501`. API docs are at
`http://localhost:8000/docs`. To stop the local stack, press Ctrl+C or run
`docker compose down` from the project root. Do not use `docker compose down -v`
unless intentionally deleting the database volume.

Compose starts the API, Streamlit frontend, and PostgreSQL. PostgreSQL is not
published on host port 5432. The API waits for database health and the frontend waits
for API health. Database records persist in the named `forgex-postgres-data` Docker
volume, but only while that volume and its Docker host/VM are preserved. Reports,
STL, PNG preview, and analysis files use the host `exports/` folder, mounted into the
API container and read-only into the frontend.

### LinuxONE deployment

Follow the separate [LinuxONE deployment checklist](./scripts/run_linuxone.md) to SSH
into a provisioned VM, install Docker and Compose, copy/clone ForgeX, configure a
private `.env`, and launch with `docker compose up --build -d`. Once the operator has
obtained the VM address from their provider and allowed the required firewall ports,
the UI will be at `http://<VM_PUBLIC_IP>:8501` and API docs at
`http://<VM_PUBLIC_IP>:8000/docs`.

These are instructions only; no LinuxONE access, public IP, or deployment success is
claimed. The standard containers do not install CadQuery, CalculiX, or OpenFOAM;
those capabilities remain optional and return `BLOCKED` when unavailable. ForgeX
outputs are not a security certification.

The generic Python local-run instructions above do not use Docker; use the Docker
commands in this section when testing the containerized stack.

## Open-source resources and attribution

ForgeX uses and builds on the following open-source projects and documentation:

- [Python](https://www.python.org/) — programming language
- [FastAPI](https://fastapi.tiangolo.com/) — API framework
- [Uvicorn](https://www.uvicorn.org/) — ASGI server
- [scikit-learn](https://scikit-learn.org/) — Random Forest training in the
  demonstration notebook
- [pandas](https://pandas.pydata.org/) and [NumPy](https://numpy.org/) — data
  preparation and numerical operations
- [joblib](https://joblib.readthedocs.io/) — notebook model serialization
- [Three.js](https://threejs.org/) — interactive 3D viewer
- [JupyterLab](https://jupyter.org/) — notebook authoring and execution
- [Streamlit](https://streamlit.io/) — engineering brief and workflow interface

Please refer to each project’s linked documentation and license for its terms.

## Disclaimer

All outputs are preliminary reference estimates, not certified engineering.
