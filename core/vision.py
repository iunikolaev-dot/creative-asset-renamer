from __future__ import annotations

import re
from pathlib import Path

from core.vision_gemini import analyze_with_gemini
from core.vision_openai import analyze_with_openai
from core.colors import extract_dominant_color
from core.scanner import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS


def load_prompt(prompt_path: str = "prompts/analyze_creative.txt") -> str:
    with open(Path(__file__).parent.parent / prompt_path, "r") as f:
        return f.read()


def detect_format(file_path: str) -> str:
    ext = Path(file_path).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    return "unknown"


def count_low_confidence(ai_result: dict) -> int:
    count = 0
    for field_data in ai_result.values():
        if isinstance(field_data, dict) and field_data.get("confidence") == "low":
            count += 1
    return count


def _normalize_ai_value(value: str) -> str:
    value = value.lower().strip()
    value = value.replace(" ", "_")
    value = re.sub(r"[^a-z0-9_\-]", "", value)
    return value if value else "x"


def _postprocess_ai_result(ai_result: dict, config: dict) -> dict:
    fields_by_name = {f["name"]: f for f in config["fields"]}

    for field_name, field_data in ai_result.items():
        if not isinstance(field_data, dict):
            continue

        raw_value = field_data.get("value", "x")
        normalized = _normalize_ai_value(raw_value)
        field_data["value"] = normalized

        field_def = fields_by_name.get(field_name)
        if field_def and normalized not in field_def.get("allowed_values", []):
            if field_data.get("confidence") != "low":
                field_data["confidence"] = "low"

    return ai_result


def analyze_file(file_path: str, config: dict, who_made_it: str) -> dict:
    prompt = load_prompt()

    result = {}

    # Step 1: auto-detect
    ad_format = detect_format(file_path)
    result["ad_format"] = {"value": ad_format, "confidence": "auto"}

    # Color detection (images only, for videos use first frame or skip)
    ext = Path(file_path).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        color = extract_dominant_color(file_path, config.get("color_map", {}))
        result["main_color"] = {"value": color, "confidence": "auto"}

    # Step 2: AI vision (Gemini primary)
    ai_result = analyze_with_gemini(file_path, prompt)
    provider_used = "gemini"

    # Step 3: Fallback if needed
    if ai_result is None or count_low_confidence(ai_result) >= config.get("ai", {}).get("fallback_trigger", 3):
        fallback = analyze_with_openai(file_path, prompt)
        if fallback is not None:
            ai_result = fallback
            provider_used = "openai"

    # Step 4: Post-process and merge
    if ai_result:
        ai_result = _postprocess_ai_result(ai_result, config)
        for field_name, field_data in ai_result.items():
            if field_name not in result:  # Don't override auto-detected fields
                result[field_name] = field_data

    # Manual fields
    result["who_made_it"] = {"value": who_made_it if who_made_it else "x", "confidence": "manual"}

    # Ensure all 13 fields exist
    for field in config["fields"]:
        if field["name"] not in result:
            result[field["name"]] = {"value": "x", "confidence": "low"}

    result["_provider"] = provider_used

    return result
