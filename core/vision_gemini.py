from __future__ import annotations

import json
from pathlib import Path
from PIL import Image


def analyze_with_gemini(file_path: str, prompt: str) -> dict | None:
    """Send file to Gemini 2.5 Flash. Return parsed JSON dict or None."""
    from core.secrets import get_secret

    api_key = get_secret("GEMINI_API_KEY")
    if not api_key:
        return None

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        ext = Path(file_path).suffix.lower()
        is_video = ext in (".mp4", ".mov", ".webm")

        if is_video:
            video_bytes = open(file_path, "rb").read()
            mime_map = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}
            mime = mime_map.get(ext, "video/mp4")
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=types.Content(
                    parts=[
                        types.Part(inline_data=types.Blob(data=video_bytes, mime_type=mime)),
                        types.Part(text=prompt),
                    ]
                ),
            )
        else:
            img = Image.open(file_path)
            img.thumbnail((1024, 1024))
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[img, prompt],
            )

        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        return json.loads(text)

    except json.JSONDecodeError:
        return None
    except Exception:
        return None
