import os
import sys
import shutil
import tempfile
import platform
import subprocess
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
load_dotenv()

from core.config import load_config
from core.vision import analyze_file
from core.namer import assemble_name, detect_conflicts

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="Creative Renamer", page_icon="🎨", layout="wide")
config = load_config()

# ── Session state defaults ───────────────────────────────────────────────────
for k, v in {
    "screen": "upload", "scan_results": {}, "uploaded_files_data": [],
    "uploaded_files_bytes": {}, "temp_paths": [], "selected_file_idx": 0,
    "versions": {}, "rename_done": False,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── CSS ──────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Reset */
    .block-container { padding: 1.5rem 2rem 2rem 2rem; max-width: 100%; }
    header[data-testid="stHeader"] { background: transparent; }
    #MainMenu, footer { visibility: hidden; }

    /* Sidebar */
    section[data-testid="stSidebar"] {
        background: #f8fafc;
        border-right: 1px solid #e2e8f0;
    }
    section[data-testid="stSidebar"] .block-container { padding-top: 1rem; }

    /* Cards */
    .card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 12px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }

    /* Section label */
    .label {
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 1px;
        color: #94a3b8;
        margin-bottom: 10px;
    }

    /* Filename preview */
    .fname-box {
        background: linear-gradient(135deg, #eef2ff, #e0e7ff);
        border: 1px solid #c7d2fe;
        border-radius: 10px;
        padding: 12px 16px;
        font-family: 'SF Mono', 'Fira Code', monospace;
        font-size: 12.5px;
        color: #312e81;
        word-break: break-all;
        line-height: 1.5;
    }

    /* Badges */
    .b { display: inline-block; padding: 2px 8px; border-radius: 6px; font-size: 10px; font-weight: 700; letter-spacing: 0.5px; }
    .b-high { background: #dcfce7; color: #166534; }
    .b-med { background: #fef9c3; color: #854d0e; }
    .b-low { background: #fee2e2; color: #991b1b; }
    .b-auto { background: #f1f5f9; color: #64748b; }
    .b-man { background: #f1f5f9; color: #64748b; }

    /* Field row */
    .field-row {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 2px;
    }
    .field-label {
        font-size: 13px;
        font-weight: 600;
        color: #334155;
        min-width: 0;
    }

    /* Upload area */
    .hero { text-align: center; padding: 20px 0 10px 0; }
    .hero h2 { color: #1e293b; margin-bottom: 4px; }
    .hero p { color: #64748b; font-size: 14px; }

    /* File count pill */
    .pill {
        background: #6366f1; color: white; padding: 3px 12px;
        border-radius: 20px; font-size: 12px; font-weight: 600;
    }

    /* Rename table */
    .rtable { width: 100%; border-collapse: separate; border-spacing: 0 4px; }
    .rtable td { padding: 8px 12px; font-size: 13px; }
    .rtable tr:nth-child(odd) td { background: #f8fafc; border-radius: 6px; }
    .rtable .old { color: #64748b; font-family: monospace; }
    .rtable .new { color: #1e293b; font-family: monospace; font-weight: 500; }
    .rtable .arrow { color: #6366f1; text-align: center; width: 40px; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ──────────────────────────────────────────────────────────────────

def save_temp_file(uploaded_file) -> str:
    temp_dir = tempfile.mkdtemp()
    temp_path = os.path.join(temp_dir, uploaded_file.name)
    with open(temp_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return temp_path


def _extract_video_thumbnail(file_path: str) -> Image.Image | None:
    """Extract first meaningful frame from video using OpenCV (no ffmpeg needed)."""
    try:
        import cv2
        cap = cv2.VideoCapture(file_path)
        if not cap.isOpened():
            return None
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        # Jump to 25% of the video for a more representative frame
        if total > 10:
            cap.set(cv2.CAP_PROP_POS_FRAMES, total // 4)
        ret, frame = cap.read()
        cap.release()
        if ret and frame is not None:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            return Image.fromarray(rgb)
    except Exception:
        pass
    return None


def show_preview(file_path: str, file_idx: int):
    ext = Path(file_path).suffix.lower()
    if ext in (".jpg", ".jpeg", ".png"):
        try:
            st.image(Image.open(file_path), use_container_width=True)
        except Exception:
            st.caption("Could not load preview")
    elif ext in (".mp4", ".mov", ".webm"):
        # Show thumbnail frame
        thumb = _extract_video_thumbnail(file_path)
        if thumb:
            st.image(thumb, use_container_width=True)
        # Also show playable video
        file_bytes = st.session_state["uploaded_files_bytes"].get(file_idx)
        if file_bytes:
            st.video(file_bytes)
        else:
            try:
                with open(file_path, "rb") as f:
                    st.video(f.read())
            except Exception:
                if not thumb:
                    st.caption("Could not load preview")


def badge(confidence: str) -> str:
    m = {"high": ("High", "b-high"), "medium": ("Med", "b-med"), "low": ("Low", "b-low"),
         "auto": ("Auto", "b-auto"), "manual": ("Manual", "b-man"), "failed": ("Fail", "b-low")}
    label, cls = m.get(confidence, ("?", "b-low"))
    return f'<span class="b {cls}">{label}</span>'


def build_filename(file_idx: int) -> str:
    result = {}
    for field in config["fields"]:
        key = f"{file_idx}_{field['name']}"
        if key in st.session_state:
            val = st.session_state[key]
            if val == "custom...":
                val = st.session_state.get(f"{file_idx}_{field['name']}_custom", "x")
            result[field["name"]] = {"value": val}
        else:
            scan = st.session_state["scan_results"].get(file_idx, {})
            result[field["name"]] = scan.get(field["name"], {"value": "x"})
    ver = st.session_state["versions"].get(file_idx)
    ext = Path(st.session_state["temp_paths"][file_idx]).suffix
    return assemble_name(result, config, version=ver, original_extension=ext)


def open_folder(path: str):
    s = platform.system()
    cmd = {"Darwin": ["open"], "Windows": ["explorer"]}.get(s, ["xdg-open"])
    subprocess.Popen(cmd + [path])


# ══════════════════════════════════════════════════════════════════════════════
# SCREEN 1: UPLOAD
# ══════════════════════════════════════════════════════════════════════════════

def screen_upload():
    _, center, _ = st.columns([1, 2, 1])
    with center:
        st.markdown('<div class="hero"><h2>🎨 Creative Renamer</h2><p>Drop your ad creatives, get structured filenames powered by AI</p></div>', unsafe_allow_html=True)

        with st.container():
            uploaded_files = st.file_uploader(
                "Upload creatives", type=["jpg", "jpeg", "png", "mp4", "mov", "webm"],
                accept_multiple_files=True, key="file_uploader", label_visibility="collapsed",
            )

        if uploaded_files:
            st.markdown(f'<span class="pill">{len(uploaded_files)} file{"s" if len(uploaded_files) != 1 else ""}</span>', unsafe_allow_html=True)

        st.markdown("")

        who_opts = next((f["allowed_values"] for f in config["fields"] if f["name"] == "who_made_it"), []) + ["custom..."]
        who = st.selectbox("Who Made It (applies to all)", who_opts, key="who_made_it_global")
        if who == "custom...":
            who = st.text_input("Creator name", key="who_made_it_custom")

        st.markdown("")
        if st.button("Scan Files with AI", disabled=not uploaded_files, type="primary", use_container_width=True):
            temps = []
            bytes_map = {}
            prog = st.progress(0, text="Preparing...")
            for i, uf in enumerate(uploaded_files):
                prog.progress(int((i / len(uploaded_files)) * 30), text=f"Saving {i+1}/{len(uploaded_files)}...")
                temps.append(save_temp_file(uf))
                bytes_map[i] = uf.getvalue()

            st.session_state["temp_paths"] = temps
            st.session_state["uploaded_files_bytes"] = bytes_map
            st.session_state["uploaded_files_data"] = [{"name": uf.name, "size": uf.size} for uf in uploaded_files]

            results = {}
            for i, tp in enumerate(temps):
                prog.progress(30 + int((i / len(temps)) * 70), text=f"Scanning {i+1}/{len(temps)}: {uploaded_files[i].name}")
                results[i] = analyze_file(tp, config, who)
            prog.progress(100, text="Done!")

            st.session_state["scan_results"] = results
            st.session_state["versions"] = {i: None for i in range(len(temps))}
            st.session_state["screen"] = "review"
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# SCREEN 2: REVIEW & EDIT
# ══════════════════════════════════════════════════════════════════════════════

def screen_review():
    results = st.session_state["scan_results"]
    temps = st.session_state["temp_paths"]
    files = st.session_state["uploaded_files_data"]
    n = len(temps)

    if n == 0:
        st.warning("No files. Go back to upload.")
        if st.button("Back"):
            st.session_state["screen"] = "upload"
            st.rerun()
        return

    idx = st.session_state["selected_file_idx"]
    if idx >= n:
        idx = 0
        st.session_state["selected_file_idx"] = 0

    # ── Sidebar: file list ──
    with st.sidebar:
        st.markdown("### 🎨 Creative Renamer")
        st.markdown('<div class="label">Files</div>', unsafe_allow_html=True)

        for i in range(n):
            ext = Path(files[i]["name"]).suffix.lower()
            icon = "🖼️" if ext in (".jpg", ".jpeg", ".png") else "🎬"
            is_sel = (i == idx)
            btn_type = "primary" if is_sel else "secondary"
            if st.button(f"{icon}  {files[i]['name']}", key=f"fb_{i}", use_container_width=True, type=btn_type):
                st.session_state["selected_file_idx"] = i
                st.rerun()

        st.markdown("---")

        if st.button("📋 Apply shared fields to all", use_container_width=True,
                     help="Copies Language, Who Made It & Details to all files"):
            for fname in ("language", "who_made_it", "details"):
                src = f"{idx}_{fname}"
                if src in st.session_state:
                    for j in range(n):
                        if j != idx:
                            st.session_state[f"{j}_{fname}"] = st.session_state[src]
            st.rerun()

        st.markdown("---")
        if st.button("← Back to Upload", use_container_width=True):
            st.session_state["screen"] = "upload"
            st.rerun()
        if st.button("Continue to Rename →", type="primary", use_container_width=True):
            st.session_state["screen"] = "confirm"
            st.rerun()

    # ── Main area: preview + fields ──
    scan = results.get(idx, {})

    preview_col, fields_col = st.columns([1, 1], gap="large")

    # ── Preview column ──
    with preview_col:
        st.markdown(f'<div class="label">Preview — {files[idx]["name"]}</div>', unsafe_allow_html=True)

        with st.container():
            show_preview(temps[idx], idx)

        provider = scan.get("_provider", "—")
        st.caption(f"Analyzed by **{provider}**")

        # Filename preview
        st.markdown("")
        st.markdown('<div class="label">Generated Filename</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="fname-box">{build_filename(idx)}</div>', unsafe_allow_html=True)

        # Version
        st.markdown("")
        vc1, vc2, vc3 = st.columns([2.5, 1, 1])
        cur_v = st.session_state["versions"].get(idx)
        with vc1:
            st.caption(f"Version: **{f'v{cur_v}' if cur_v and cur_v > 1 else '—'}**")
        with vc2:
            if st.button("➕", key=f"vu_{idx}", help="Add version"):
                st.session_state["versions"][idx] = (st.session_state["versions"].get(idx) or 1) + 1
                st.rerun()
        with vc3:
            if st.button("➖", key=f"vd_{idx}", help="Remove version"):
                c = st.session_state["versions"].get(idx)
                st.session_state["versions"][idx] = (c - 1) if c and c > 1 else None
                st.rerun()

    # ── Fields column ──
    with fields_col:
        st.markdown('<div class="label">Fields</div>', unsafe_allow_html=True)

        for field in config["fields"]:
            fn = field["name"]
            fd = scan.get(fn, {"value": "x", "confidence": "low"})
            ai_val = fd.get("value", "x") if isinstance(fd, dict) else str(fd)
            conf = fd.get("confidence", "low") if isinstance(fd, dict) else "low"

            opts = list(field.get("allowed_values", []))
            if field.get("allow_custom", False):
                opts.append("custom...")

            if ai_val in opts:
                di = opts.index(ai_val)
            elif ai_val and ai_val != "x":
                opts.insert(0, ai_val)
                di = 0
            else:
                di = 0

            # Field label + badge on one line, dropdown below
            st.markdown(f'<div class="field-row"><span class="field-label">{field["display_name"]}</span> {badge(conf)}</div>', unsafe_allow_html=True)

            sel = st.selectbox(fn, opts, index=di, key=f"{idx}_{fn}", label_visibility="collapsed")

            if sel == "custom...":
                st.text_input("Custom value", key=f"{idx}_{fn}_custom", label_visibility="collapsed", placeholder="Type custom value...")


# ══════════════════════════════════════════════════════════════════════════════
# SCREEN 3: CONFIRM & RENAME
# ══════════════════════════════════════════════════════════════════════════════

def screen_confirm():
    temps = st.session_state["temp_paths"]
    files = st.session_state["uploaded_files_data"]
    n = len(temps)

    if n == 0:
        st.warning("No files.")
        if st.button("Back"):
            st.session_state["screen"] = "upload"
            st.rerun()
        return

    _, center, _ = st.columns([0.5, 3, 0.5])

    with center:
        st.markdown("## Confirm & Rename")
        st.caption(f"{n} files ready")
        st.markdown("")

        names = detect_conflicts([build_filename(i) for i in range(n)])

        # Table
        rows = ""
        for i in range(n):
            rows += f'<tr><td class="old">{files[i]["name"]}</td><td class="arrow">→</td><td class="new">{names[i]}</td></tr>'
        st.markdown(f'<table class="rtable">{rows}</table>', unsafe_allow_html=True)

        # Conflicts
        if len(names) != len(set(names)):
            st.warning("Duplicate names detected — suffixes (_a, _b) added.")

        st.markdown("")

        mode = st.radio("Output mode", ["Copy to output folder (recommended)", "Rename in place"], index=0, key="output_mode")
        out_dir = str(Path(__file__).parent / "renamed")
        if "Copy" in mode:
            out_dir = st.text_input("Output folder", value=out_dir, key="output_dir")

        st.markdown("")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("← Back to Review", use_container_width=True):
                st.session_state["screen"] = "review"
                st.rerun()
        with c2:
            if st.button("Rename All", type="primary", use_container_width=True):
                os.makedirs(out_dir, exist_ok=True)
                prog = st.progress(0)
                ok = 0
                for i in range(n):
                    prog.progress(int(((i + 1) / n) * 100), text=f"Renaming {i+1}/{n}...")
                    src = temps[i]
                    dst = os.path.join(out_dir, names[i])
                    try:
                        shutil.copy2(src, dst)
                        ok += 1
                    except Exception as e:
                        st.error(f"Failed: {files[i]['name']} — {e}")
                prog.progress(100, text="Done!")
                st.session_state["rename_done"] = True
                st.session_state["output_dir"] = out_dir
                st.rerun()

        if st.session_state.get("rename_done"):
            d = st.session_state.get("output_dir", out_dir)
            st.success(f"All files renamed! Saved to `{d}`")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("📂 Open Folder", type="primary", use_container_width=True):
                    open_folder(d)
            with c2:
                if st.button("🔄 Start Over", use_container_width=True):
                    for k in list(st.session_state.keys()):
                        del st.session_state[k]
                    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# ROUTER
# ══════════════════════════════════════════════════════════════════════════════

{"upload": screen_upload, "review": screen_review, "confirm": screen_confirm}[st.session_state.get("screen", "upload")]()
