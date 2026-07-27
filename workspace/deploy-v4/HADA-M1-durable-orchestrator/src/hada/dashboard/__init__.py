from importlib.resources import files
from pathlib import Path


def dashboard_asset_path(name: str) -> Path:
    """Return a filesystem path for a bundled Command Centre asset."""
    if name not in {"index.html", "app.css", "app.js", "status.json"}:
        raise ValueError(f"unknown dashboard asset: {name}")
    return Path(str(files("hada.dashboard").joinpath(name)))
