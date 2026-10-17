# ForgeX Streamlit Frontend

This Streamlit application is a conversational client for the ForgeX FastAPI backend.
It does not implement engineering calculations, recommendations, or CAD generation.
The main screen pairs a chat workflow with a live engineering canvas; the sidebar
contains backend settings, the session ID, workflow progress, and reset controls.

## Run locally

From the ForgeX project root, open two terminals.

**Terminal 1 — API backend**

```powershell
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

**Terminal 2 — Streamlit frontend**

```powershell
pip install -r frontend/requirements.txt
python -m streamlit run frontend/app.py
```

Open <http://localhost:8501>. The API defaults to `http://127.0.0.1:8000`. To use a
different backend URL, set `FORGEX_API_URL` before starting Streamlit:

```powershell
$env:FORGEX_API_URL = "http://127.0.0.1:8000"
python -m streamlit run frontend/app.py
```

## Workflow

1. Choose a product family and submit a plain-language request in chat.
2. Answer the backend's targeted clarification questions in chat. For non-gripper
   families, product-specific inputs are available in the canvas and are sent to the
   backend with the clarification.
3. Once the backend reports that required inputs are present, the frontend submits the
   brief for confirmation and requests design screening.
4. Review returned alternatives, statuses, calculations, and evidence in the live
   canvas. Follow-up questions are sent to the backend's design Q&A endpoint.
5. Use the export and opt-in analysis section to request a Markdown report or reference
   STL for a returned design.
6. Report and STL download controls appear only when the backend returned an artifact
   path; STL also requires the real non-empty file to be accessible to Streamlit.

The report content is returned by the backend and can be previewed in the UI. An
interactive STL viewer and PNG preview are shown only when real artifacts are returned
and accessible to the Streamlit process. For STL downloads, the Streamlit host must
share access to the backend's `exports/` directory.
If the API is remote or uses a separate filesystem, the UI will show the returned path
and status but will not offer an inaccessible STL download.
Use the sidebar reset control to start a new workflow. API persistence depends on the
backend's configured storage: in-memory sessions are cleared when the backend restarts.

The sidebar lets you set the API URL and session ID, check backend health, track
workflow progress, and reset the local UI session. Resetting starts a new frontend
session ID; it does not delete backend data.

## Status and limitations

Statuses, calculations, assumptions, comparison values, and evidence are displayed
from backend responses without recomputation. `BLOCKED`, `REVIEW`, `ESTIMATED`, and
other API-returned statuses are not upgraded or reinterpreted by the frontend.
Reference designs and CAD are not optimized, validated, certified, simulated, or
manufacturing-ready geometry.

The Streamlit server makes API requests from Python to FastAPI, not from the browser.
Therefore browser CORS is not required for this implementation. If a future frontend
uses browser-side `fetch`, configure FastAPI CORS to allow
`http://localhost:8501`.
