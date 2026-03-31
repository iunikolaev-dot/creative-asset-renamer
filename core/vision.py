from __future__ import annotations

import re
from pathlib import Path

from core.vision_gemini import analyze_with_gemini
from core.vision_openai import analyze_with_openai
from core.colors import extract_dominant_color
from core.library import ValueLibrary
from core.prompt_builder import build_prompt_with_library
from core.scanner import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS


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


_UI_ARTIFACTS = {
    "arrow", "arrow right", "arrow left", "arrow up", "arrow down",
    "chevron", "chevron right", "chevron left", "chevron down", "chevron up",
    "icon", "button", "caret", "dropdown", "expand", "collapse",
    "close", "check circle", "info", "warning", "error", "spinner",
}


def _normalize_ai_value(value: str) -> str:
    """Normalize AI output: lowercase, underscores→spaces, strip junk, reject UI artifacts."""
    value = value.lower().strip()
    # Underscores are filename separators — values must use spaces
    value = value.replace("_", " ")
    value = re.sub(r"[^a-z0-9 /\-]", "", value)
    value = re.sub(r" +", " ", value).strip()
    if not value or value in _UI_ARTIFACTS:
        return "x"
    return value


def classify_file_status(result: dict) -> str:
    """Classify a file as 'ready', 'needs_review', or 'failed'."""
    low_count = 0
    failed_count = 0
    for f in result.values():
        if isinstance(f, dict):
            conf = f.get("confidence", "")
            if conf == "low":
                low_count += 1
            elif conf == "failed":
                failed_count += 1
    if failed_count > 0 or low_count >= 3:
        return "failed"
    elif low_count > 0:
        return "needs_review"
    return "ready"


def analyze_file(
    file_path: str,
    config: dict,
    shared_fields: dict,
    library: ValueLibrary,
    # Legacy compat — old callers may pass who_made_it as positional
    _legacy_who: str | None = None,
) -> dict:
    """Analyze a single creative file and return a result dict.

    shared_fields: mapping of field_name → value for fields pre-set on the
    upload screen (who_made_it, topic, main_object, main_usp, etc.).
    Any pre-set field is injected as confidence='manual' and never overridden
    by AI — this is the mechanism for session-level consistency rules.
    """
    # Backwards-compat: old callers pass who_made_it as 3rd positional arg (a string)
    if isinstance(shared_fields, str):
        _legacy_who = shared_fields
        shared_fields = {}
    if _legacy_who is not None and "who_made_it" not in shared_fields:
        shared_fields = dict(shared_fields)
        shared_fields["who_made_it"] = _legacy_who

    # Normalise & drop blank values so they don't override AI
    locked: dict[str, str] = {
        k: v.strip() for k, v in shared_fields.items() if v and v.strip() and v.strip() != "—"
    }

    # Build prompt — hint AI about any locked fields so it focuses on the rest
    hint_lines = []
    for k, v in locked.items():
        hint_lines.append(f"  - {k}: \"{v}\" (already known, do not change)")
    extra_hint = (
        "\n\nSome fields are already confirmed for this upload session:\n" + "\n".join(hint_lines)
        if hint_lines else ""
    )
    prompt = build_prompt_with_library(config, library) + extra_hint

    result = {}

    # Step 1: auto-detect format
    ad_format = detect_format(file_path)
    result["ad_format"] = {"value": ad_format, "confidence": "auto"}

    # Color detection (images only)
    ext = Path(file_path).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        color = extract_dominant_color(file_path, config.get("color_map", {}))
        result["main_color"] = {"value": color, "confidence": "auto"}

    # Step 2: Inject locked fields BEFORE AI so they're already in result
    for field_name, value in locked.items():
        result[field_name] = {"value": value, "confidence": "manual"}

    # Step 3: AI vision (Gemini primary)
    ai_result = analyze_with_gemini(file_path, prompt)
    provider_used = "gemini"

    # Step 4: Fallback if needed
    if ai_result is None or count_low_confidence(ai_result) >= config.get("ai", {}).get("fallback_trigger", 3):
        fallback = analyze_with_openai(file_path, prompt)
        if fallback is not None:
            ai_result = fallback
            provider_used = "openai"

    # Step 5: Library matching — map AI suggestions to canonical values
    # Locked fields already in result — skip them
    if ai_result:
        for field_name, field_data in ai_result.items():
            if not isinstance(field_data, dict):
                continue
            if field_name in result:  # Don't override auto-detected or locked fields
                continue

            raw_value = _normalize_ai_value(field_data.get("value", "x"))
            match = library.match(field_name, raw_value)

            result[field_name] = {
                "value": match["value"],
                "confidence": match["confidence"],
                "ai_raw": raw_value,
                "matched_via": match["matched_via"],
            }

    # Ensure all configured fields exist
    for field in config["fields"]:
        if field["name"] not in result:
            result[field["name"]] = {"value": "x", "confidence": "low"}

    result["_provider"] = provider_used

    return result
