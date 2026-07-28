from pathlib import Path

import yaml

from hada.models import HadaConfig


def load_config(path: Path) -> HadaConfig:
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    return HadaConfig.model_validate(raw)
