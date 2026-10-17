from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from api import routes_exports
from api.main import app
from api.session_store import session_store


def test_web_workbench_is_served_at_app_and_root_redirects():
    with TestClient(app) as client:
        page = client.get("/app/")
        studio = client.get("/app/studio.html")
        embedded_studio = client.get("/app/studio.html?embedded=1")
        viewer = client.get("/app/try.html")
        house = client.get("/app/Models/house_model.html")
        economy_obj = client.get("/app/Models/house_A_50k.obj")
        comfort_obj = client.get("/app/Models/house_B_85k.obj")
        premium_obj = client.get("/app/Models/house_C_140k.obj")
        app_without_slash = client.get("/app", follow_redirects=False)
        root = client.get("/", follow_redirects=False)

    source_directory = Path(__file__).parent.parent / "frontend_web"
    app_shell_path = source_directory / "app.html"
    studio_path = source_directory / "studio.html"
    viewer_path = source_directory / "try.html"
    house_path = source_directory / "Models" / "house_model.html"
    assert page.status_code == 200
    assert page.content == app_shell_path.read_bytes()
    assert page.headers["cache-control"] == "no-cache, no-store, must-revalidate"
    assert "Design Studio" in page.text and "3D Viewer" in page.text and "Wireframe" in page.text
    assert "grid-template-columns: 260px minmax(0, 1fr);" in page.text
    assert "height: 100dvh;" in page.text
    assert "border-right: 1px solid var(--line);" in page.text
    assert "height: 56px;" in page.text
    assert "border-bottom: 1px solid var(--line);" in page.text
    assert "flex: 0 0 auto;" in page.text
    assert "white-space: nowrap;" in page.text
    assert "overflow-x: auto;" in page.text
    assert "scrollbar-width: none;" in page.text
    assert "padding: 8px 14px;" in page.text
    assert "font-size: 15px;" in page.text and "font-weight: 500;" in page.text
    assert "stroke: currentColor;" in page.text
    assert ".forgex-tab[aria-selected=\"true\"]" in page.text
    assert "background: #212124;" in page.text
    assert "color: #fff;" in page.text
    assert 'id="sidebar-new"' in page.text
    assert 'id="sidebar-history"' in page.text
    assert 'id="share-link"' in page.text and 'id="download-chat"' in page.text
    assert 'id="mobile-menu"' in page.text and "max-width: 767px" in page.text
    assert "forgex-chat-${date}.md" in page.text
    assert 'src="/app/studio.html?embedded=1"' in page.text
    assert "outline-offset: 2px;" in page.text
    assert 'src="/app/try.html"' in page.text
    assert 'src="/app/Models/house_model.html"' in page.text
    assert "forgex-studio" in page.text and "forgex-3d" in page.text and "forgex-wireframe" in page.text
    assert "SHOW_HOUSE_MODEL" in page.text and "LOAD_HOUSE" in page.text
    assert studio.status_code == 200
    assert studio.content == studio_path.read_bytes()
    assert embedded_studio.content == studio_path.read_bytes()
    assert "html.embedded aside,html.embedded .top{display:none}" in embedded_studio.text
    assert "ForgeX script loaded, DOM ready:" in studio.text
    assert 'id="f"' in studio.text
    assert "function showHouseModel(tier)" in studio.text
    assert "economy" in studio.text and "comfort" in studio.text and "premium" in studio.text
    assert r"\b50k\b|\$50,000" in studio.text
    assert r"\b85k\b|\$85,000" in studio.text
    assert r"\b140k\b|\$140,000" in studio.text
    assert "Show 3D Model" in studio.text
    assert viewer.status_code == 200
    assert viewer.content == viewer_path.read_bytes()
    assert "three-canvas-container" in viewer.text
    assert "OrbitControls.js" in viewer.text
    assert "id=\"length-input\"" in viewer.text
    assert "function exportActiveSTL()" in viewer.text
    assert house.status_code == 200
    assert house.content == house_path.read_bytes()
    assert "LOAD_HOUSE" in house.text
    assert "pick(index)" in house.text and "setMode(1)" in house.text
    assert economy_obj.status_code == comfort_obj.status_code == premium_obj.status_code == 200
    assert economy_obj.content == (source_directory / "Models" / "house_A_50k.obj").read_bytes()
    assert comfort_obj.content == (source_directory / "Models" / "house_B_85k.obj").read_bytes()
    assert premium_obj.content == (source_directory / "Models" / "house_C_140k.obj").read_bytes()
    assert studio.headers["cache-control"] == "no-cache, no-store, must-revalidate"
    assert viewer.headers["cache-control"] == "no-cache, no-store, must-revalidate"
    assert app_without_slash.status_code == 307
    assert app_without_slash.headers["location"] == "http://testserver/app/"
    assert app_without_slash.headers["cache-control"] == "no-cache, no-store, must-revalidate"
    assert root.status_code == 307
    assert root.headers["location"] == "/app/"


def test_stl_download_requires_and_returns_real_generated_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_exports, "PROJECT_ROOT", tmp_path)
    session_id = "web-download-test"
    export_dir = tmp_path / "exports" / session_id
    export_dir.mkdir(parents=True)
    artifact = export_dir / "ALT-A_reference_concept.stl"
    artifact.write_bytes(b"solid actual-stl\nendsolid actual-stl\n")
    relative_path = Path("exports") / session_id / artifact.name
    session_store.clear()
    session_store.save_or_create(
        session_id,
        {
            "design_result": {"alternatives": [{"id": "ALT-A"}]},
            "cad_artifacts": [
                {
                    "design_id": "ALT-A",
                    "status": "CREATED",
                    "artifact_path": relative_path.as_posix(),
                }
            ],
        },
    )
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/design/ALT-A/cad",
                params={"session_id": session_id},
            )
            missing = client.get(
                "/api/design/ALT-B/cad",
                params={"session_id": session_id},
            )
    finally:
        session_store.clear()

    assert response.status_code == 200
    assert response.content == artifact.read_bytes()
    assert response.headers["content-type"].startswith("model/stl")
    assert missing.status_code == 404
