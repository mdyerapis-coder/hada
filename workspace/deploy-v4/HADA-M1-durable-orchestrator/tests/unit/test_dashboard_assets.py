import json

import pytest

from hada.dashboard import dashboard_asset_path


def test_dashboard_assets_are_bundled() -> None:
    for asset in ("index.html", "app.css", "app.js", "status.json"):
        path = dashboard_asset_path(asset)
        assert path.exists()
        assert path.stat().st_size > 100


def test_dashboard_snapshot_preserves_execution_boundary() -> None:
    payload = json.loads(dashboard_asset_path("status.json").read_text())
    assert payload["operating_mode"] == "LOCAL_ONLY"
    assert payload["execution_state"] == "READY_NOT_EXECUTED"
    assert payload["metrics"]["active_tasks"] == 0
    assert payload["milestone"]["status"] == "external_review_required"


def test_documentation_stays_inside_the_dark_dashboard() -> None:
    html = dashboard_asset_path("index.html").read_text()
    javascript = dashboard_asset_path("app.js").read_text()
    assert 'href="../../../docs/' not in html
    assert html.count('class="doc-card"') == 6
    assert 'id="document-reader"' in html
    assert "const documents =" in javascript


def test_dashboard_rejects_unknown_assets() -> None:
    with pytest.raises(ValueError, match="unknown dashboard asset"):
        dashboard_asset_path("../../config/hada.yaml")
