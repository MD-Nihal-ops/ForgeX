# ForgeX Product Specification (v1)

This document is the source of product truth for ForgeX v1. Implementation must follow it. Where code and this specification disagree, this specification wins until it is explicitly revised.

ForgeX is **not** finite-element analysis, **not** a test laboratory, and **not** a safety or regulatory certification body. Closed-form estimates for FDM 3D-printed plastics are the only numerical engineering method in v1.

---

## 1. Product vision

ForgeX is a web-based AI engineering workspace. A user describes a mechanical product in plain language. ForgeX turns that idea into a **traceable, calculated, and manufacturable** design package.

The product exists to close the gap between “I need a part” and “I can print, assemble, and justify it”:

- Capture intent as a structured engineering brief.
- Formalize measurable requirements, loads, envelopes, and safety constraints.
- Propose a small set of parametric design alternatives.
- Evaluate those alternatives with **deterministic, inspectable calculations**.
- Bind every requirement to evidence in a Requirement–Evidence Ledger.
- Export a manufacturing package (bill of materials, assembly steps, Markdown report, and STL when CAD is available).

AI is an **assistive parser and explainer**, not an oracle. Language models may help structure briefs, name alternatives, and draft prose. They must never be the source of material properties, component ratings, simulation results, CAD geometry, numerical answers, or certification claims.

The long-term vision is a single engineering workspace that grows from 3D-printed end-effectors and brackets toward robotic subsystems, machinery, vehicles, and built environments—always with evidence, always with explicit uncertainty, never with invented physics.

---

## 2. MVP scope (v1)

v1 ships **only** FDM 3D-printable hardware in these two families:

1. **Servo-driven grippers** (parallel-jaw and servo-jaw style parametric templates).
2. **Simple structural brackets** (for example L-brackets and similarly constrained printable mounts).

Allowed manufacturing method: **`fdm_3d_print` only**.

In-scope capabilities:

- Natural-language brief intake and structured `EngineeringBrief`.
- Performance requirements, load conditions, envelope dimensions, budget (USD), operating environment, and safety constraints (closed-form safety factors, not certification).
- A small catalog of **versioned** materials, hobby servos, FDM printers, and design templates. Catalog values are data, not LLM output.
- Two or more parametric **design alternatives** per project, with explicit parameters, pros/cons, and status (`draft`, `proposed`, `selected`, `infeasible`, `superseded`).
- Closed-form calculations listed in [§9](#9-required-engineering-calculations).
- Design comparison on mass, cost, print time, safety factor, and requirement pass/fail.
- Requirement–Evidence Ledger with the four evidence statuses in [§5](#5-evidence-statuses).
- STL export via CadQuery **when CAD libraries are available**.
- Markdown engineering report and JSON/project export.
- Docker image that runs on **LinuxONE (`s390x`)** with CAD optional (see [§10](#10-docker-and-linuxone-deployment)).

v1 product types that may appear in data models for forward compatibility (`simple_printable_part`, `simple_assembly`) are **not** first-class user workflows. The UI must not present them as supported product families. Requests that are not a gripper or a simple bracket must be rejected or marked `BLOCKED` with notes, not silently stretched into an unsupported category.

---

## 3. Out of scope for v1

The following are **forbidden** in v1 product claims, UI, calculations, and exports:

- Electronics design (PCBs, firmware, power electronics, sensors beyond “buy this catalog servo”).
- Building / architectural design, structural codes for buildings, HVAC, and civil engineering.
- Computational fluid dynamics (CFD).
- Advanced finite-element analysis (FEA), topology optimization, nonlinear material models, contact/impact simulation, vibration/modal analysis, fatigue life, and thermal simulation.
- Safety certification, CE/UL/ISO claims, load ratings presented as tested or certified, or any language that a design is “safe to use” as a legal or standards conclusion.
- Machining, injection molding, sheet metal, welding, and other non-FDM processes as primary manufacture.
- Multi-body dynamics, full robot kinematics/path planning, and control-system design.
- Vehicles, machinery frames, pressure vessels, lifting equipment for people, medical devices, and load-bearing built environments.
- Invented or web-scraped material cards, servo torque curves, or printer profiles that are not in the project catalog.
- Live generation of CAD kernels by the LLM (the model must not emit STEP/STL/CadQuery scripts as if they were verified geometry).
- Cloud-only features that prevent LinuxONE/offline calculation, ledger, and Markdown export.
- User accounts, multi-tenant SaaS billing, and collaborative editing (not required for v1).

If a user asks for an out-of-scope capability, ForgeX must say so, keep the ledger honest (`BLOCKED` / `UNVERIFIED` as appropriate), and must not fabricate a substitute analysis.

---

## 4. Seven-stage engineering workflow

Every project walks the same pipeline. Stages may be revisited, but a later stage must not silently overwrite earlier evidence. Numerical work happens only in Stage 4 (and is **displayed** in later stages).

| Stage | Name | Purpose | Gate to the next stage |
| --- | --- | --- | --- |
| **1** | **Brief capture** | User describes the product. Optional LLM parses text into a candidate `EngineeringBrief`. User confirms project name, product type (gripper or bracket), purpose, loads, envelope, material preference, budget, environment, and assumptions. | Valid `EngineeringBrief` with at least one performance requirement and one load condition. Product type in MVP scope. |
| **2** | **Requirements formalization** | Convert the brief into measurable requirements, load cases, envelope limits, and safety constraints. Record assumptions explicitly. | Requirement set is complete enough to evaluate; unknown quantities are listed, not guessed. |
| **3** | **Design proposal** | Instantiate parametric alternatives from **catalog templates** (not from free-form LLM geometry). Each alternative has an id, parameters, and status. | At least one proposed alternative whose parameters are fully specified or explicitly incomplete. |
| **4** | **Deterministic calculation** | Run the ordered Python calculation pipeline (grip, servo, bending, safety, mass, cost, print time as applicable). Persist `CalculationResult` records with equation ids, inputs, outputs, units, and evidence status. | Every attempted calculation is a function return value; missing inputs yield `BLOCKED`, not invented numbers. |
| **5** | **Comparison** | Tabulate alternatives: mass, cost, print time, governing safety factor, requirement results. User selects one design or marks others infeasible/superseded. | A single `selected` design, or an explicit decision to stop. |
| **6** | **Requirement–Evidence Ledger** | Map each requirement to a design decision, a pointer to calculation/catalog/assumption evidence, a result (`pass` / `fail` / `unknown` / `not_applicable`), and an evidence status. | No requirement row without evidence text and status. `BLOCKED` rows include notes. |
| **7** | **Manufacturing export** | Produce the manufacturing package: BOM, material recommendation, dimensions, tolerances, assembly instructions, known limitations, required physical tests, Markdown report, project JSON, and STL if CAD is available. | Package states limitations; STL omitted with `BLOCKED` notes on `s390x` or when CadQuery is absent. |

**Workflow rules**

- Offline-first: Stages 2–7 must run without an LLM. Stage 1 may use an LLM only to draft structure; the user (or deterministic fallback parser) owns the saved brief.
- Recalculation: changing parameters invalidates downstream calculation results and ledger rows until Stage 4 is re-run.
- Traceability: exports must cite calculation names/equation ids and evidence statuses. They must not flatten `ESTIMATED` results into unmarked numbers.
- Physical tests listed in Stage 7 are **required of the builder**. ForgeX does not perform or certify them.

---

## 5. Evidence statuses

Exactly four statuses exist. Do not add others in v1.

### VERIFIED

Used only when:

- The numeric or catalog fact comes from a **deterministic Python function** or a **checked-in catalog record**, and
- Inputs are complete and in range, and
- The requirement result is **not** `unknown`.

`VERIFIED` never means “tested in a lab” or “certified.” It means “reproducible from this repo’s functions and data.”

`not_applicable` + `VERIFIED` is allowed only with notes explaining why the requirement does not apply.

### ESTIMATED

Closed-form or heuristic results that are intentionally approximate (print-time heuristics, infill-adjusted mass, catalog properties used outside a tightly validated regime, derated servo torque, bending of printed plastic treated as a simple beam). The equation still comes from Python; the status tells the user the model is coarse.

### UNVERIFIED

A value or claim is present but **not** backed by a completed calculation or catalog row (user-supplied guess, unresolved preference, qualitative statement). The UI must not treat `UNVERIFIED` numbers as calculation outputs.

The LLM must not fill `UNVERIFIED` gaps with made-up quantities. Leave them unverified or mark `BLOCKED`.

### BLOCKED

The pipeline cannot complete the check. Typical causes: missing load, unknown material id, CAD library unavailable, product type out of scope, division by zero / invalid geometry parameters, servo not in catalog.

**`BLOCKED` always requires notes** that state what is missing or why the step cannot run. A `CalculationResult` or ledger row with status `BLOCKED` and empty notes is invalid.

**Consistency rules**

- `VERIFIED` + result `unknown` is invalid.
- Do not upgrade `ESTIMATED` to `VERIFIED` because the LLM “sounds confident.”
- Do not mark CAD/STL `VERIFIED` on platforms where CadQuery/OCP is not loaded.

---

## 6. Numerical results must come from deterministic Python functions

**Hard rule:** every number that ForgeX presents as an engineering result—forces, torques, stresses, safety factors, masses, costs, print times, derived dimensions used in those formulas—must be the return value of a **pure, deterministic Python function** in `src/forgex/calc/` (or an equally test-covered calculation module).

Implications:

- Same inputs → same outputs on every machine (amd64 and `s390x`), independent of LLM availability.
- Functions take explicit numeric/catalog inputs and return structured `CalculationResult` data: `name`, `equation` (formula id), `inputs`, `output_value`, `unit`, `evidence_status`, `notes`.
- No hidden randomness, no network calls, no “ask the model for a typical PLA yield strength.”
- The LLM, Streamlit widgets, and report templates may **display** numbers; they may not **compute** them in prose or JavaScript.
- Unit tests are mandatory for each formula id in [§9](#9-required-engineering-calculations).
- If inputs are missing or invalid, the function (or its caller) records `BLOCKED` with notes. It must not return a plausible dummy.

SI units are canonical in storage and calculation. UI may show convenience units but must convert through shared unit helpers, not ad hoc literals in prompts.

---

## 7. LLM prohibition: no invented engineering facts

The language model **may**:

- Parse natural language into a **candidate** brief for the user to edit.
- Suggest requirement wording that the user accepts or rejects.
- Propose **names, descriptions, pros, and cons** for alternatives whose **parameters** come from templates.
- Draft assembly-instruction prose and limitation text that restates known package fields.
- Explain a calculation **after** the Python result exists, citing the function inputs and outputs.

The language model **must not**:

- Invent or override **material properties** (density, allowable stress, modulus, cost per kg, temperature ratings).
- Invent or override **component specs** (servo stall torque, voltage, mass, horn radius, printer speed, nozzle diameter).
- Invent **simulations**, FEA plots, CFD, “I ran a contact study,” or fake experimental data.
- Invent **CAD files**, meshes, STL bytes, CadQuery scripts presented as geometry, or dimensions not taken from the parametric model.
- Invent **certifications**, safety approvals, code compliance, or “this will hold X kg in service.”
- Invent numerical results, formula constants, derate factors, or catalog ids.
- Upgrade evidence status.

If a required catalog row is missing, the correct behavior is `BLOCKED` (or `UNVERIFIED` for a user-owned qualitative field)—never a hallucinated datasheet.

System prompts, agent schemas, and code review must enforce this boundary. Any LLM output that includes quantities must be **schema-validated and stripped of numbers that did not originate in Python or catalogs** before persistence.

---

## 8. Required Streamlit screens

v1 is a Streamlit multipage app. These screens are required. Additional decorative pages are not a substitute.

| Screen | File (convention) | Required contents |
| --- | --- | --- |
| **Home** | `app.py` | Product name, one-paragraph vision, MVP scope, disclaimer (not FEA / not certification), entry to the workflow, CAD availability indicator (on/off). |
| **1 · Brief** | `pages/1_Brief.py` | Natural-language input; structured brief fields; product type limited to gripper and bracket; save/load project. Optional LLM parse with explicit “candidate only” labeling. |
| **2 · Requirements** | `pages/2_Requirements.py` | Editable performance requirements, load conditions, envelope, safety constraints, assumptions. No silent insertion of numeric targets by the LLM. |
| **3 · Designs** | `pages/3_Designs.py` | Parametric alternatives from templates; key parameters; status; catalog material/servo/printer selection. |
| **4 · Calculations** | `pages/4_Calculations.py` | Table of `CalculationResult` rows: name, equation id, inputs, output, unit, evidence status, notes. Trigger to re-run the Python pipeline. No editable “result” fields that bypass functions. |
| **5 · Compare** | `pages/5_Compare.py` | Side-by-side alternatives; selection control; infeasible/superseded actions. |
| **6 · Ledger** | `pages/6_Ledger.py` | Full Requirement–Evidence Ledger; filters by status/result; `BLOCKED` notes visible. |
| **7 · Export** | `pages/7_Export.py` | Manufacturing package preview; BOM; limitations; required physical tests; download Markdown/JSON; STL download **or** a clear CAD-unavailable/`s390x` message. |

Shared UI rules: show evidence badges on every numeric engineering value; warn when CadQuery is missing; persist session/project so refresh does not drop a confirmed brief.

---

## 9. Required engineering calculations

All calculations are closed-form or documented heuristics for **3D-printed plastics and hobby servos**. Formula identifiers are stable and must appear on results and in the Markdown report.

| ID | Name | Applies to | Intent | Typical evidence |
| --- | --- | --- | --- | --- |
| **GRIP-01** | Required grip force | Grippers | Force needed to hold the payload given mass, gravity, friction/assumption factor, and load orientation. | `ESTIMATED` (friction and payload assumptions) or `BLOCKED` if payload/load missing. |
| **SRV-01** | Required servo torque | Grippers | Torque at the actuator from grip force and jaw/lever geometry. | `ESTIMATED` or `BLOCKED`. |
| **SRV-02** | Available grip from servo | Grippers | Grip force implied by **catalog** stall (or rated) torque, derate factor from code/constants, and the same geometry. Compare to GRIP-01. | `ESTIMATED` (derate and printed-mechanism losses). `BLOCKED` if servo not in catalog. |
| **BND-01** | Bending stress | Grippers and brackets | Simple beam (or equivalent closed-form) stress from load, span, and section modulus of the parametric cross-section. | `ESTIMATED`. Not FEA. |
| **SF-01** | Safety factor | Grippers and brackets | Allowable (catalog) stress divided by BND-01 (or governing closed-form demand). Compare to `min_safety_factor` when specified. | `ESTIMATED`. Never a certification. |
| **MAS-01** | Mass | Both | Volume from parametric geometry × catalog density × infill fraction (and bought-item catalog masses). | `ESTIMATED` when infill/volume is heuristic; `BLOCKED` without material density. |
| **CST-01** | Cost (USD) | Both | Printed mass × catalog material cost plus buy-items from catalog unit costs. | `ESTIMATED`. |
| **PRT-01** | FDM print time | Both | Heuristic from volume/path estimates and **catalog** printer speed parameters. | `ESTIMATED`. `BLOCKED` without printer profile. |

**Pipeline order (v1):** GRIP-01 → SRV-01 → SRV-02 → BND-01 → SF-01 → MAS-01 → CST-01 → PRT-01, skipping families that do not apply (brackets skip grip/servo unless a future template truly needs them). Skipped steps are omitted or `not_applicable` in the ledger—not filled with zeros.

**Constants and derates** live in version-controlled Python (`src/forgex/calc/constants.py`) or catalogs. Changing a constant is a code/data change, not a prompt change.

**Geometry:** parametric solids for jaws/brackets are generated by Python geometry modules. Volume used in MAS-01/PRT-01 must come from those modules or an equivalent deterministic approximation documented in notes—not from the LLM. If CadQuery is absent, use the documented fallback volume model and mark mass/print-time `ESTIMATED` or `BLOCKED` per implementation rules, never `VERIFIED` as CAD-true.

---

## 10. Docker and LinuxONE deployment

v1 must be deployable as a container on **IBM LinuxONE** (`s390x`) as well as conventional `amd64`.

Requirements:

- **Base:** Python **3.11+**, Streamlit app entry `streamlit run app.py` (or equivalent).
- **Required image contents:** application code, `requirements.txt` runtime dependencies (Streamlit, Pydantic, Pandas, NumPy, SciPy, httpx, python-dotenv). Do **not** require CadQuery/OCP in the default `s390x` image.
- **Optional CAD extra:** CadQuery may be installed on architectures where wheels/libs exist (typically `amd64`). STL export is best-effort.
- **Behavior without CAD:** calculations, comparison, ledger, project persistence, and Markdown/JSON export **must still run**. STL is omitted; ledger/export notes record CAD `BLOCKED` or unavailable.
- **LLM optional:** no API key is required to complete Stages 2–7. Missing LLM → brief must be filled manually; no degraded fake calculations.
- **Determinism:** calculation tests must pass on `s390x`. Avoid CPU-specific numeric paths.
- **Config:** environment variables / `.env` for LLM endpoint, data paths, and feature flags (`CAD_ENABLED`, etc.). Secrets never baked into the image.
- **Health:** container listens on a documented HTTP port; process runs as a non-root user when the host allows.
- **Persistence:** project files and exports mount on a volume; the image is stateless aside from that mount.
- **Docs:** Dockerfile, compose or run examples, and a LinuxONE note: “CAD/STL off; engineering workspace on.”

LinuxONE is a first-class target, not a best-effort afterthought. Features that cannot compile on `s390x` must be optional extras, not hard dependencies.

---

## 11. Future roadmap

v1 is the narrowest honest product: **printable grippers and simple brackets** with closed-form evidence.

Later expansions, in order of increasing system complexity. Each wave needs new catalogs, new deterministic calculators, new evidence rules, and an explicit decision that v1 methods are insufficient—not a prompt that “now we design cars.”

1. **Brackets (expanded)** — additional printable joint and mounting families, fastener catalogs, richer section libraries, still FDM-first.
2. **Robotic components** — more end-effectors, links, housings, and servo/gearbox selections; still not full robot controllers or certified collaborative robots.
3. **Machinery** — frames, simple mechanisms, and machine elements with expanded closed-form (and later, optional licensed analysis) tools.
4. **Vehicles** — subsystems and fixtures first; whole-vehicle dynamics, crash, and homologation remain out of scope until a dedicated specification says otherwise.
5. **Built environments** — fixtures and components before architecture; building codes, occupancy, and structural certification are a different product.

Roadmap items do not leak into v1 UI copy as if they were available. The Home screen may mention the direction in one sentence; it must not offer those product types as working modes.

---

## Non-goals reminder (all versions until specified otherwise)

ForgeX helps a builder **reason in the open**: formulas, inputs, catalogs, statuses, and tests they must still perform. It does not replace a licensed professional engineer, a test lab, or a notified body.
