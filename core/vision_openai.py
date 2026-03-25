from __future__ import annotations

import json
import os
import base64
from pathlib import Path
from PIL import Image
from openai import OpenAI

from core.scanner import extract_video_frames


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


def _encode_image_b64(file_path: str) -> str:
    with open(file_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _image_media_type(file_path: str) -> str:
    ext = Path(file_path).suffix.lower()
    return {"jpg": "jpeg", "jpeg": "jpeg", "png": "png"}.get(ext.lstrip("."), "jpeg")


def analyze_with_openai(file_path: str, prompt: str) -> dict | None:
    from core.secrets import get_secret
    api_key = get_secret("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        client = OpenAI(api_key=api_key)

        ext = Path(file_path).suffix.lower()
        is_video = ext in (".mp4", ".mov", ".webm")

        content = [{"type": "text", "text": prompt}]

        if is_video:
            frames = extract_video_frames(file_path, count=3)
            for frame_bytes in frames:
                b64 = base64.b64encode(frame_bytes).decode("utf-8")
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                })
            if not frames:
                return None
        else:
            file_path = _resize_image_if_needed(file_path)
            b64 = _encode_image_b64(file_path)
            media = _image_media_type(file_path)
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/{media};base64,{b64}"},
            })

        response = client.chat.completions.create(
            model="gpt-5.4",
            messages=[{"role": "user", "content": content}],
            max_tokens=1000,
        )

        text = response.choices[0].message.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        return json.loads(text)

    except json.JSONDecodeError:
        return None
    except Exception:
        return None
