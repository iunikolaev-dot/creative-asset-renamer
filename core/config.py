from __future__ import annotations

import yaml
from pathlib import Path


def load_config(config_path: str | None = None) -> dict:
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config.yaml"
    else:
        config_path = Path(config_path)

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    # Sort fields by position
    config["fields"] = sorted(config["fields"], key=lambda f: f["position"])

    return config


def get_field_by_name(config: dict, name: str) -> dict | None:
    for field in config["fields"]:
        if field["name"] == name:
            return field
    return None
