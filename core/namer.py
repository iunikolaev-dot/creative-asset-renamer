from __future__ import annotations

import re
from pathlib import Path


def _normalize_value(value: str) -> str:
    value = value.lower().strip()
    value = value.replace(" ", "-")
    value = value.replace("_", "-")
    value = re.sub(r"[^a-z0-9\-]", "", value)
    return value if value else "x"


def assemble_name(
    fields_dict: dict,
    config: dict,
    version: int | None = None,
    original_extension: str = ".jpg",
) -> str:
    """Returns filename stem only (no extension). Caller adds extension when saving."""
    separator = config.get("separator", "_")
    placeholder = config.get("empty_placeholder", "x")
    max_len = config.get("max_filename_length", 200)

    parts = []
    for field in sorted(config["fields"], key=lambda f: f["position"]):
        if not field.get("include_in_filename", True):
            continue
        field_data = fields_dict.get(field["name"], {})
        value = field_data.get("value", placeholder) if isinstance(field_data, dict) else str(field_data)
        if not value or value.strip() == "":
            value = placeholder
        parts.append(_normalize_value(value))

    name = separator.join(parts)

    if version and version > 1:
        name += f"_v{version}"

    if len(name) > max_len:
        name = name[:max_len]

    return name


def detect_conflicts(names: list[str]) -> list[str]:
    """Resolve duplicate stems by appending _a, _b, etc."""
    counts: dict[str, int] = {}
    for name in names:
        counts[name] = counts.get(name, 0) + 1

    result = []
    seen: dict[str, int] = {}
    for name in names:
        if counts[name] > 1:
            idx = seen.get(name, 0)
            suffix = chr(ord("a") + idx)
            result.append(f"{name}_{suffix}")
            seen[name] = idx + 1
        else:
            result.append(name)

    return result
