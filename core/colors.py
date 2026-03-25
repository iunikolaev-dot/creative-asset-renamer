from __future__ import annotations

import math
from pathlib import Path
from PIL import Image

try:
    import colorgram
except ImportError:
    colorgram = None


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _color_distance(c1: tuple[int, int, int], c2: tuple[int, int, int]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(c1, c2)))


def _nearest_named_color(rgb: tuple[int, int, int], color_map: dict) -> str:
    best_name = "other"
    best_dist = float("inf")
    for hex_val, name in color_map.items():
        dist = _color_distance(rgb, _hex_to_rgb(hex_val))
        if dist < best_dist:
            best_dist = dist
            best_name = name
    return best_name


def extract_dominant_color(image_path: str, color_map: dict) -> str:
    if colorgram is None:
        return _fallback_dominant_color(image_path, color_map)

    try:
        colors = colorgram.extract(image_path, 3)
        if not colors:
            return "other"
        top = colors[0].rgb
        return _nearest_named_color((top.r, top.g, top.b), color_map)
    except Exception:
        return _fallback_dominant_color(image_path, color_map)


def _fallback_dominant_color(image_path: str, color_map: dict) -> str:
    try:
        with Image.open(image_path) as img:
            img = img.convert("RGB").resize((50, 50))
            pixels = list(img.getdata())
            avg_r = sum(p[0] for p in pixels) // len(pixels)
            avg_g = sum(p[1] for p in pixels) // len(pixels)
            avg_b = sum(p[2] for p in pixels) // len(pixels)
            return _nearest_named_color((avg_r, avg_g, avg_b), color_map)
    except Exception:
        return "other"
