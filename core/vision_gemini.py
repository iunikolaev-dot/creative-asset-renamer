from __future__ import annotations

import json
import os
from pathlib import Path
from PIL import Image
from google import genai


def _resize_image_if_needed(file_path: str, max_size: int = 1024) -> str:
    ext = Path(file_path).suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png"):
        return file_path

    with Image.open(file_path) as img:
        w, h = img.size
        if max(w, h) <= max_size:
            return file_path

        ratio = max_size / max(w, h)
        new_w, new_h = int(w * ratio), int(h * ratio)
        resized = img.resize((new_w, new_h), Image.LANCZOS)

        resized_path = file_path + "_resized" + ext
        resized.save(resized_path, quality=85)
        return resized_path


def analyze_with_gemini(file_path: str, prompt: str) -> dict | None:
    from core.secrets import get_secret
    api_key = get_secret("GEMINI_API_KEY")
    if not api_key:
        return None

    try:
        client = genai.Client(api_key=api_key)

        ext = Path(file_path).suffix.lower()
        is_video = ext in (".mp4", ".mov", ".webm")

        if not is_video:
            file_path = _resize_image_if_needed(file_path)

        uploaded = client.files.upload(file=file_path)

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[uploaded, prompt],
        )

        text = response.text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        return json.loads(text)

    except json.JSONDecodeError:
        return None
    except Exception:
        return None
