from __future__ import annotations

import subprocess
import json
from pathlib import Path
from PIL import Image

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm"}
ALL_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS


def scan_file(path: str) -> dict:
    p = Path(path)
    ext = p.suffix.lower()

    if ext not in ALL_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext}")

    result = {
        "file_path": str(p),
        "file_name": p.name,
        "extension": ext,
        "file_size_bytes": p.stat().st_size,
    }

    if ext in IMAGE_EXTENSIONS:
        result["file_type"] = "image"
        with Image.open(p) as img:
            result["width"], result["height"] = img.size
        result["has_audio"] = False
    else:
        result["file_type"] = "video"
        result.update(_probe_video(str(p)))

    return result


def _probe_video(path: str) -> dict:
    info = {"width": 0, "height": 0, "has_audio": False, "duration": 0.0}
    try:
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", "-show_format", path,
        ]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        data = json.loads(out.stdout)

        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video" and info["width"] == 0:
                info["width"] = int(stream.get("width", 0))
                info["height"] = int(stream.get("height", 0))
            if stream.get("codec_type") == "audio":
                info["has_audio"] = True

        fmt = data.get("format", {})
        info["duration"] = float(fmt.get("duration", 0))
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError, KeyError):
        pass
    return info


def scan_folder(path: str) -> list[dict]:
    p = Path(path)
    results = []
    for f in sorted(p.iterdir()):
        if f.suffix.lower() in ALL_EXTENSIONS:
            results.append(scan_file(str(f)))
    return results


def extract_video_frame(video_path: str, position_pct: float = 0.5) -> bytes | None:
    try:
        probe_cmd = [
            "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", video_path,
        ]
        result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=10)
        duration = float(result.stdout.strip())
        timestamp = duration * position_pct

        cmd = [
            "ffmpeg", "-ss", str(timestamp), "-i", video_path,
            "-vframes", "1", "-f", "image2pipe", "-vcodec", "png", "-",
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=15)
        if result.returncode == 0 and result.stdout:
            return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass
    return None


def extract_video_frames(video_path: str, count: int = 3) -> list[bytes]:
    positions = [(i + 1) / (count + 1) for i in range(count)]
    frames = []
    for pos in positions:
        frame = extract_video_frame(video_path, pos)
        if frame:
            frames.append(frame)
    return frames
