from __future__ import annotations

from pathlib import Path

from core.library import ValueLibrary


def build_prompt_with_library(config: dict, library: ValueLibrary) -> str:
    """Build the AI prompt with library values injected per field."""
    base_path = Path(__file__).parent.parent / "prompts" / "analyze_creative.txt"
    base = base_path.read_text(encoding="utf-8")

    field_instructions = []
    for field in config["fields"]:
        name = field["name"]
        detection = field.get("detection", "")
        if detection in ("ai_suggested", "ai_detected", "auto_ai"):
            if name in library.fields:
                values = library.fields[name]["values"]
                values_str = ", ".join(values)
                field_instructions.append(
                    f'  "{name}": SELECT from [{values_str}]. '
                    f'If none fit, use your best guess but set confidence to "low".'
                )

    if field_instructions:
        return (
            base
            + "\n\nALLOWED VALUES PER FIELD:\n"
            + "\n".join(field_instructions)
        )
    return base
