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
from core.vision import analyze_file, classify_file_status
from core.namer import assemble_name, detect_conflicts
from core.library import ValueLibrary

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="Creative Renamer", page_icon="🎨", layout="wide")
config = load_config()

# ── Load library ─────────────────────────────────────────────────────────────
library_dir = str(Path(__file__).parent / config.get("library_dir", "library"))
library = ValueLibrary(library_dir)

# ── Session state ────────────────────────────────────────────────────────────
for k, v in {
    "screen": "upload", "scan_results": {}, "uploaded_files_data": [],
    "uploaded_files_bytes": {}, "temp_paths": [], "statuses": {},
    "versions": {}, "rename_done": False, "selected_for_rename": set(),
    "filter_status": "needs_review", "new_custom_values": [],
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Notion-style CSS ─────────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    /* Global */
    html, body, .stApp, .stApp * { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important; }
    .block-container { max-width: 1100px !important; padding: 2rem 1rem 3rem 1rem; margin: 0 auto; }
    header[data-testid="stHeader"] { background: transparent; }
    #MainMenu, footer { visibility: hidden; }
    section[data-testid="stSidebar"] { display: none; }

    /* Typography */
    .page-title { font-size: 28px; font-weight: 700; color: #191919; margin: 0 0 2px 0; letter-spacing: -0.5px; }
    .page-sub { font-size: 14px; color: #9b9b9b; margin: 0 0 24px 0; font-weight: 400; }
    .section-label {
        font-size: 11px; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.8px; color: #b0b0b0; margin-bottom: 8px; padding-bottom: 6px;
        border-bottom: 1px solid #f0f0f0;
    }

    /* Badges */
    .tag {
        display: inline-block; padding: 1px 7px; border-radius: 4px;
        font-size: 10px; font-weight: 600; letter-spacing: 0.3px;
        vertical-align: middle; margin-left: 4px;
    }
    .tag-high { background: #dbeddb; color: #2b593f; }
    .tag-med  { background: #fdecc8; color: #7b5c00; }
    .tag-low  { background: #ffe2dd; color: #93000a; }
    .tag-auto { background: #f0f0f0; color: #787774; }
    .tag-man  { background: #f0f0f0; color: #787774; }

    /* Status cards */
    .stat-card {
        border-radius: 8px; padding: 16px 20px; text-align: center;
    }
    .stat-card h2 { margin: 0; font-size: 32px; font-weight: 700; }
    .stat-card p { margin: 4px 0 0 0; font-size: 12px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.5px; }
    .stat-ready { background: #f0faf0; border: 1px solid #c6e6c6; }
    .stat-ready h2 { color: #2b593f; }
    .stat-ready p { color: #5a8a5a; }
    .stat-review { background: #fef9ef; border: 1px solid #f0dca8; }
    .stat-review h2 { color: #7b5c00; }
    .stat-review p { color: #9b7d2a; }
    .stat-failed { background: #fef2f2; border: 1px solid #f0c0c0; }
    .stat-failed h2 { color: #93000a; }
    .stat-failed p { color: #b04040; }

    /* File row */
    .file-row {
        display: flex; align-items: center; gap: 12px;
        padding: 10px 14px; border-radius: 6px; border: 1px solid #f0f0f0;
        margin-bottom: 6px; font-size: 13px; background: #fff;
    }
    .file-row:hover { background: #fafafa; }
    .file-row .fname { flex: 1; font-family: 'SFMono-Regular', monospace; font-size: 12px; color: #37352f; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .file-row .new-name { flex: 1.5; font-family: 'SFMono-Regular', monospace; font-size: 12px; color: #37352f; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .file-row .arrow { color: #b0b0b0; font-size: 14px; flex-shrink: 0; }

    /* Dot indicators */
    .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; flex-shrink: 0; }
    .dot-green { background: #2b593f; }
    .dot-yellow { background: #d4a017; }
    .dot-red { background: #c0392b; }

    /* Field label */
    .flabel { font-size: 12px; font-weight: 600; color: #37352f; margin-bottom: 2px; }

    /* Upload hero */
    .hero-title { font-size: 30px; font-weight: 700; color: #191919; letter-spacing: -0.5px; margin: 0; }
    .hero-sub { font-size: 14px; color: #9b9b9b; margin: 4px 0 20px 0; }

    /* Pill */
    .pill { background: #f0f0f0; color: #37352f; padding: 3px 10px; border-radius: 4px; font-size: 12px; font-weight: 500; }

    /* Filename preview */
    .fname-box {
        background: #f7f7f5; border: 1px solid #e8e8e5; border-radius: 6px;
        padding: 10px 14px; font-family: 'SFMono-Regular', monospace;
        font-size: 12px; color: #37352f; word-break: break-all; line-height: 1.6;
    }

    /* Rename table */
    .rt { width: 100%; border-collapse: collapse; }
    .rt td { padding: 8px 10px; font-size: 12.5px; border-bottom: 1px solid #f0f0f0; }
    .rt .o { color: #9b9b9b; font-family: monospace; }
    .rt .a { color: #b0b0b0; text-align: center; width: 30px; }
    .rt .n { color: #37352f; font-family: monospace; font-weight: 500; }

    /* Issues tag */
    .issue-tag {
        display: inline-block; padding: 2px 8px; border-radius: 4px;
        font-size: 10px; font-weight: 500; background: #fef3cd; color: #856404;
        margin-right: 4px; margin-bottom: 2px;
    }

    /* Selectbox sizing */
    div[data-baseweb="select"] { font-size: 13px !important; }
    div[data-baseweb="select"] > div { min-height: 36px !important; }

    /* Prevent expander header from overlapping widgets below it */
    details > summary { position: relative; z-index: 1; }
    details { position: relative; z-index: 0; }
    div[data-testid="stExpander"] { isolation: isolate; }

    /* Expand file uploader list to show ~10 rows */
    [data-testid="stFileUploader"] [data-testid="stFileUploaderFileList"] {
        max-height: 420px !important;
        overflow-y: auto !important;
    }
    [data-testid="stFileUploader"] [data-testid="stFileUploaderFileList"] > div {
        max-height: 420px !important;
    }
</style>
""", unsafe_allow_html=True)


# ── Helpers ──────────────────────────────────────────────────────────────────

def save_temp_file(uploaded_file) -> str:
    temp_dir = tempfile.mkdtemp()
    temp_path = os.path.join(temp_dir, uploaded_file.name)
    with open(temp_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return temp_path


def get_thumbnail(file_path: str) -> Image.Image | None:
    ext = Path(file_path).suffix.lower()
    if ext in (".jpg", ".jpeg", ".png"):
        try:
            return Image.open(file_path)
        except Exception:
            return None
    elif ext in (".mp4", ".mov", ".webm"):
        try:
            import cv2
            cap = cv2.VideoCapture(file_path)
            if not cap.isOpened():
                return None
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if total > 10:
                cap.set(cv2.CAP_PROP_POS_FRAMES, total // 4)
            ret, frame = cap.read()
            cap.release()
            if ret and frame is not None:
                return Image.fromarray(frame[:, :, ::-1])
        except Exception:
            return None
    return None


def tag(confidence: str) -> str:
    m = {"high": ("High", "tag-high"), "medium": ("Med", "tag-med"), "low": ("Low", "tag-low"),
         "auto": ("Auto", "tag-auto"), "manual": ("Manual", "tag-man"), "failed": ("Fail", "tag-low")}
    label, cls = m.get(confidence, ("?", "tag-low"))
    return f'<span class="tag {cls}">{label}</span>'


def status_dot(status: str) -> str:
    cls = {"ready": "dot-green", "needs_review": "dot-yellow", "failed": "dot-red"}.get(status, "dot-yellow")
    return f'<span class="dot {cls}"></span>'


def get_field_options(field: dict) -> list[str]:
    """Get dropdown options from library CSV or fallback."""
    name = field["name"]
    if name in library.fields:
        opts = list(library.fields[name]["values"])
    else:
        opts = []
    if field.get("allow_custom", False):
        opts.append("custom...")
    return opts


def build_filename(file_idx: int) -> str:
    result = {}
    scan = st.session_state["scan_results"].get(file_idx, {})
    for field in config["fields"]:
        key = f"{file_idx}_{field['name']}"
        if key in st.session_state:
            val = st.session_state[key]
            if val == "custom...":
                val = st.session_state.get(f"{file_idx}_{field['name']}_custom", "x")
            result[field["name"]] = {"value": val}
        else:
            result[field["name"]] = scan.get(field["name"], {"value": "x"})
    ver = st.session_state["versions"].get(file_idx)
    return assemble_name(result, config, version=ver)


def build_filename_with_ext(file_idx: int) -> str:
    """Returns stem + original extension for use when actually saving files."""
    stem = build_filename(file_idx)
    ext = Path(st.session_state["temp_paths"][file_idx]).suffix.lower()
    return stem + ext


def get_issues(result: dict) -> list[str]:
    """Get list of fields that need attention."""
    issues = []
    for field in config["fields"]:
        fd = result.get(field["name"], {})
        if isinstance(fd, dict):
            conf = fd.get("confidence", "")
            matched = fd.get("matched_via", "")
            if conf == "low" or matched == "unmatched":
                issues.append(field["display_name"])
    return issues


def open_folder(path: str):
    s = platform.system()
    subprocess.Popen({"Darwin": ["open"], "Windows": ["explorer"]}.get(s, ["xdg-open"]) + [path])


def pick_folder_dialog() -> str | None:
    """Open a native OS folder-picker dialog. Returns path string or None."""
    s = platform.system()
    try:
        if s == "Darwin":
            result = subprocess.run(
                ["osascript", "-e",
                 'POSIX path of (choose folder with prompt "Choose output folder for renamed files")'],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                return result.stdout.strip().rstrip("/")
        elif s == "Windows":
            result = subprocess.run(
                ["powershell", "-Command",
                 "(New-Object -ComObject Shell.Application)"
                 ".BrowseForFolder(0,'Choose output folder',0).Self.Path"],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        else:
            result = subprocess.run(
                ["zenity", "--file-selection", "--directory",
                 "--title=Choose output folder"],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                return result.stdout.strip()
    except Exception:
        pass
    return None


def is_streamlit_cloud() -> bool:
    """Heuristic: Streamlit Cloud sets HOSTNAME or mounts at /mount/src."""
    return (
        os.environ.get("STREAMLIT_SHARING_MODE") == "1"
        or os.path.exists("/mount/src")
        or "streamlit.app" in os.environ.get("SERVER_NAME", "")
    )


def collect_custom_values() -> list[dict]:
    """Find values that were manually entered and don't exist in the library."""
    new_values = []
    results = st.session_state["scan_results"]
    for file_idx in results:
        for field in config["fields"]:
            key = f"{file_idx}_{field['name']}"
            if key in st.session_state and st.session_state[key] == "custom...":
                custom_val = st.session_state.get(f"{file_idx}_{field['name']}_custom", "")
                if custom_val and field["name"] in library.fields:
                    if custom_val.lower() not in library.fields[field["name"]]["entries"]:
                        new_values.append({"field": field["name"], "value": custom_val.lower()})
    # Deduplicate
    seen = set()
    unique = []
    for v in new_values:
        k = (v["field"], v["value"])
        if k not in seen:
            seen.add(k)
            unique.append(v)
    return unique


# ══════════════════════════════════════════════════════════════════════════════
# SCREEN 1: UPLOAD
# ══════════════════════════════════════════════════════════════════════════════

def screen_upload():
    st.markdown("")
    _, center, _ = st.columns([1, 2, 1])
    with center:
        st.markdown('<p class="hero-title">🎨 Creative Renamer</p>', unsafe_allow_html=True)
        st.markdown('<p class="hero-sub">Drop your ad creatives. AI names them. You review exceptions.</p>', unsafe_allow_html=True)

        # ── Shared Fields FIRST ─────────────────────────────────────────────────
        st.markdown(
            '<p style="font-size:11px;font-weight:600;color:#9ca3af;letter-spacing:.08em;'
            'text-transform:uppercase;margin:16px 0 8px;">Applies to all files</p>',
            unsafe_allow_html=True,
        )
        sf_col1, sf_col2, sf_col3 = st.columns(3)

        with sf_col1:
            st.markdown('<p style="font-size:12px;font-weight:500;color:#374151;margin-bottom:2px;">Who Made It</p>', unsafe_allow_html=True)
            who_opts = ["—"] + library.get_values("who_made_it") + ["custom..."]
            who = st.selectbox("who_made_it", who_opts, key="who_made_it_global", label_visibility="collapsed")
            if who == "custom...":
                who = st.text_input("who_made_it_custom", key="who_made_it_custom_input", placeholder="Type name...", label_visibility="collapsed")

        with sf_col2:
            st.markdown('<p style="font-size:12px;font-weight:500;color:#374151;margin-bottom:2px;">Topic</p>', unsafe_allow_html=True)
            topic_opts = ["—"] + library.get_values("topic") + ["custom..."]
            topic = st.selectbox("topic", topic_opts, key="topic_global", label_visibility="collapsed")
            if topic == "custom...":
                topic = st.text_input("topic_custom", key="topic_custom_input", placeholder="Type topic...", label_visibility="collapsed")

        with sf_col3:
            st.markdown('<p style="font-size:12px;font-weight:500;color:#374151;margin-bottom:2px;">Main Product</p>', unsafe_allow_html=True)
            usp_opts = ["—"] + library.get_values("main_usp") + ["custom..."]
            main_usp = st.selectbox("main_usp", usp_opts, key="main_usp_global", label_visibility="collapsed")
            if main_usp == "custom...":
                main_usp = st.text_input("main_usp_custom", key="main_usp_custom_input", placeholder="Type product...", label_visibility="collapsed")

        st.markdown('<div style="margin:16px 0 8px;border-top:1px solid #f0f0f0;"></div>', unsafe_allow_html=True)

        # ── File Uploader ───────────────────────────────────────────────────────
        uploaded_files = st.file_uploader(
            "Upload", type=["jpg", "jpeg", "png", "mp4", "mov", "webm"],
            accept_multiple_files=True, key="file_uploader", label_visibility="collapsed",
        )

        # ── Scrollable file list ────────────────────────────────────────────────
        if uploaded_files:
            img_exts = {".jpg", ".jpeg", ".png"}
            vid_exts = {".mp4", ".mov", ".webm"}
            n_img = sum(1 for f in uploaded_files if Path(f.name).suffix.lower() in img_exts)
            n_vid = sum(1 for f in uploaded_files if Path(f.name).suffix.lower() in vid_exts)
            parts = []
            if n_img:
                parts.append(f"{n_img} image{'s' if n_img != 1 else ''}")
            if n_vid:
                parts.append(f"{n_vid} video{'s' if n_vid != 1 else ''}")
            count_text = " · ".join(parts) if parts else f"{len(uploaded_files)} files"

            st.markdown(
                f'<p style="font-size:11px;font-weight:600;color:#9ca3af;letter-spacing:.08em;'
                f'text-transform:uppercase;margin:12px 0 6px;">{count_text}</p>',
                unsafe_allow_html=True,
            )

            # Show all files in a compact scrollable area (max 240px ~= 10 rows)
            rows_html = ""
            for uf in uploaded_files:
                ext = Path(uf.name).suffix.lower()
                icon = "🎬" if ext in vid_exts else "🖼️"
                size_kb = uf.size // 1024
                size_str = f"{size_kb / 1024:.1f} MB" if size_kb > 1024 else f"{size_kb} KB"
                rows_html += (
                    f'<div style="display:flex;align-items:center;gap:8px;padding:5px 8px;'
                    f'border-bottom:1px solid #f5f5f5;font-size:12px;color:#37352f;">'
                    f'<span style="font-size:14px;">{icon}</span>'
                    f'<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{uf.name}</span>'
                    f'<span style="color:#9b9b9b;flex-shrink:0;">{size_str}</span>'
                    f'</div>'
                )
            st.markdown(
                f'<div style="border:1px solid #e8e8e5;border-radius:8px;'
                f'max-height:240px;overflow-y:auto;background:#fafafa;">{rows_html}</div>',
                unsafe_allow_html=True,
            )

        # Build shared_fields dict — only include fields that were actually set
        shared_fields: dict[str, str] = {}
        if who and who not in ("—", ""):
            shared_fields["who_made_it"] = who
        if topic and topic not in ("—", ""):
            shared_fields["topic"] = topic
        if main_usp and main_usp not in ("—", ""):
            shared_fields["main_usp"] = main_usp

        st.markdown("")
        n = len(uploaded_files) if uploaded_files else 0
        btn_label = f"Scan {n} files with AI" if n > 0 else "Scan Files with AI"

        # All 3 shared fields must be filled before scanning
        fields_missing = [
            label for label, val in [
                ("Who Made It", who), ("Topic", topic), ("Main Product", main_usp)
            ] if not val or val in ("—", "")
        ]
        if fields_missing:
            st.markdown(
                f'<p style="font-size:12px;color:#d97706;margin:0 0 6px 0;">'
                f'⚠ Please fill in: {", ".join(fields_missing)}</p>',
                unsafe_allow_html=True,
            )
        scan_disabled = not uploaded_files or bool(fields_missing)
        if st.button(btn_label, disabled=scan_disabled, type="primary", use_container_width=True):
            temps, bmap = [], {}
            prog = st.progress(0, text="Preparing...")
            for i, uf in enumerate(uploaded_files):
                prog.progress(int((i / len(uploaded_files)) * 20), text=f"Saving {i+1}/{len(uploaded_files)}...")
                temps.append(save_temp_file(uf))
                bmap[i] = uf.getvalue()
            st.session_state.update({
                "temp_paths": temps,
                "uploaded_files_bytes": bmap,
                "uploaded_files_data": [{"name": uf.name, "size": uf.size} for uf in uploaded_files],
                "shared_fields": shared_fields,
            })

            results = {}
            statuses = {"ready": [], "needs_review": [], "failed": []}
            for i, tp in enumerate(temps):
                pct = 20 + int((i / len(temps)) * 80)
                prog.progress(pct, text=f"Scanning {i+1}/{len(temps)}: {uploaded_files[i].name}")
                result = analyze_file(tp, config, shared_fields, library)
                status = classify_file_status(result)
                results[i] = result
                statuses[status].append(i)

            prog.progress(100, text="Done!")

            # Pre-select all ready files for rename
            selected = set(statuses["ready"])

            st.session_state.update({
                "scan_results": results,
                "statuses": statuses,
                "versions": {i: None for i in range(len(temps))},
                "selected_for_rename": selected,
                "screen": "dashboard",
            })
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# SCREEN 2: BATCH DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

def _get_small_thumbnail(file_path: str, size: int = 48) -> Image.Image | None:
    """Get a small square thumbnail for table rows."""
    thumb = get_thumbnail(file_path)
    if thumb is None:
        return None
    try:
        img = thumb.copy()
        # Crop to square from center
        w, h = img.size
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        img = img.crop((left, top, left + side, top + side))
        img = img.resize((size, size), Image.LANCZOS)
        return img
    except Exception:
        return None


def screen_dashboard():
    results = st.session_state["scan_results"]
    temps = st.session_state["temp_paths"]
    files = st.session_state["uploaded_files_data"]
    statuses = st.session_state["statuses"]
    n = len(temps)

    if n == 0:
        st.warning("No files.")
        if st.button("Back"):
            st.session_state["screen"] = "upload"
            st.rerun()
        return

    st.markdown('<p class="page-title">Batch Dashboard</p>', unsafe_allow_html=True)
    st.markdown(f'<p class="page-sub">{n} files scanned — review exceptions, then rename</p>', unsafe_allow_html=True)

    # ── Compact status bar ──
    n_ready = len(statuses.get("ready", []))
    n_review = len(statuses.get("needs_review", []))
    n_failed = len(statuses.get("failed", []))

    st.markdown(
        f'<div style="display:flex;gap:16px;align-items:center;margin:0 0 16px 0;'
        f'font-size:12px;font-weight:500;">'
        f'<span style="color:#2b593f;">● {n_ready} ready</span>'
        f'<span style="color:#856404;">● {n_review} needs review</span>'
        f'<span style="color:#93000a;">● {n_failed} failed</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Filter Controls ──
    filter_options = ["All", "Needs Review", "Ready", "Failed"]
    default_idx = 1 if n_review > 0 else 0
    selected_filter = st.radio(
        "Filter", filter_options, index=default_idx,
        horizontal=True, key="dash_filter", label_visibility="collapsed",
    )

    # Build filtered file list
    filter_map = {
        "All": list(range(n)),
        "Ready": statuses.get("ready", []),
        "Needs Review": statuses.get("needs_review", []),
        "Failed": statuses.get("failed", []),
    }
    visible_files = filter_map.get(selected_filter, list(range(n)))

    # ── Table Header ──
    st.markdown(
        '<div style="display:flex;align-items:center;gap:8px;padding:4px 8px 6px 8px;font-size:10px;'
        'font-weight:600;text-transform:uppercase;letter-spacing:0.6px;color:#b0b0b0;'
        'border-bottom:1px solid #e8e8e5;margin-bottom:4px;">'
        '<span style="width:24px;"></span>'
        '<span style="width:44px;"></span>'
        '<span style="flex:1.3;">Original</span>'
        '<span style="flex:1.8;">New Name</span>'
        '<span style="flex:1.4;">Fields to Review</span>'
        '<span style="width:24px;"></span>'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── Batch Table with per-file checkboxes and thumbnails ──
    for i in visible_files:
        result = results[i]
        status = classify_file_status(result)
        issues = get_issues(result)
        new_name = build_filename(i)

        # Row: checkbox | thumb | original | new name | missing fields | status
        col_cb, col_thumb, col_orig, col_new, col_issues, col_status = st.columns(
            [0.25, 0.35, 1.3, 1.8, 1.4, 0.3], vertical_alignment="center"
        )

        with col_cb:
            default_checked = i in st.session_state.get("selected_for_rename", set())
            checked = st.checkbox("sel", value=default_checked, key=f"cb_{i}", label_visibility="collapsed")
            if checked:
                st.session_state["selected_for_rename"].add(i)
            else:
                st.session_state["selected_for_rename"].discard(i)

        with col_thumb:
            small_thumb = _get_small_thumbnail(temps[i])
            if small_thumb:
                st.image(small_thumb, width=44)
            else:
                ext = Path(files[i]["name"]).suffix.lower()
                icon = "🎬" if ext in (".mp4", ".mov", ".webm") else "🖼️"
                st.markdown(
                    f'<div style="width:44px;height:44px;background:#f5f5f5;border-radius:6px;'
                    f'display:flex;align-items:center;justify-content:center;font-size:18px;">{icon}</div>',
                    unsafe_allow_html=True,
                )

        with col_orig:
            st.markdown(
                f'<span style="font-family:monospace;font-size:11px;color:#9b9b9b;">'
                f'{files[i]["name"]}</span>',
                unsafe_allow_html=True,
            )

        with col_new:
            st.markdown(
                f'<span style="font-family:monospace;font-size:11px;color:#37352f;font-weight:500;">'
                f'{new_name}</span>',
                unsafe_allow_html=True,
            )

        with col_issues:
            if issues:
                issues_html = " ".join(
                    f'<span style="display:inline-block;padding:1px 6px;border-radius:3px;'
                    f'font-size:10px;font-weight:500;background:#fef3cd;color:#856404;'
                    f'margin:1px 2px 1px 0;">{iss}</span>'
                    for iss in issues
                )
                st.markdown(f'<div>{issues_html}</div>', unsafe_allow_html=True)

        with col_status:
            st.markdown(status_dot(status), unsafe_allow_html=True)

        # ── Inline Editor for yellow/red rows ──
        if status in ("needs_review", "failed"):
            with st.expander("Edit", expanded=False):
                col_preview, col_fields = st.columns([1, 2.5])

                with col_preview:
                    thumb = get_thumbnail(temps[i])
                    if thumb:
                        st.image(thumb, width=200)
                    else:
                        fb = st.session_state["uploaded_files_bytes"].get(i)
                        if fb:
                            st.video(fb)

                    # Live filename preview
                    st.markdown('<div class="section-label" style="margin-top:12px;">Output filename</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="fname-box">{build_filename(i)}</div>', unsafe_allow_html=True)

                with col_fields:
                    # Separate problem fields from OK fields
                    problem_fields = []
                    ok_fields = []
                    for field in config["fields"]:
                        fn = field["name"]
                        fd = result.get(fn, {"value": "x", "confidence": "low"})
                        conf = fd.get("confidence", "low") if isinstance(fd, dict) else "low"
                        matched = fd.get("matched_via", "") if isinstance(fd, dict) else ""
                        if conf == "low" or matched == "unmatched":
                            problem_fields.append(field)
                        else:
                            ok_fields.append(field)

                    # Show problem fields with dropdowns
                    if problem_fields:
                        st.markdown('<div class="section-label">Needs fixing</div>', unsafe_allow_html=True)
                    for field in problem_fields:
                        fn = field["name"]
                        fd = result.get(fn, {"value": "x", "confidence": "low"})
                        ai_val = fd.get("value", "x") if isinstance(fd, dict) else str(fd)
                        conf = fd.get("confidence", "low") if isinstance(fd, dict) else "low"
                        ai_raw = fd.get("ai_raw", "") if isinstance(fd, dict) else ""

                        opts = get_field_options(field)
                        if not opts:
                            opts = [ai_val]
                        if ai_val in opts:
                            di = opts.index(ai_val)
                        elif ai_val and ai_val != "x":
                            opts.insert(0, ai_val)
                            di = 0
                        else:
                            di = 0

                        hint = f"  ·  AI suggested: *{ai_raw}*" if ai_raw and ai_raw != ai_val else ""
                        st.markdown(f'<div class="flabel">{field["display_name"]} {tag(conf)}</div>', unsafe_allow_html=True)
                        if hint:
                            st.caption(hint)
                        sel = st.selectbox(fn, opts, index=di, key=f"{i}_{fn}", label_visibility="collapsed")
                        if sel == "custom...":
                            st.text_input("custom", key=f"{i}_{fn}_custom", label_visibility="collapsed", placeholder="Type value...")

                    # OK fields — hidden behind toggle, no dropdowns unless expanded
                    if ok_fields:
                        show_all = st.toggle("Show all fields", value=False, key=f"show_all_{i}")
                        if show_all:
                            for field in ok_fields:
                                fn = field["name"]
                                fd = result.get(fn, {"value": "x", "confidence": "high"})
                                ai_val = fd.get("value", "x") if isinstance(fd, dict) else str(fd)
                                conf = fd.get("confidence", "high") if isinstance(fd, dict) else "high"

                                opts = get_field_options(field)
                                if not opts:
                                    opts = [ai_val]
                                if ai_val in opts:
                                    di = opts.index(ai_val)
                                elif ai_val and ai_val != "x":
                                    opts.insert(0, ai_val)
                                    di = 0
                                else:
                                    di = 0

                                st.markdown(f'<div class="flabel">{field["display_name"]} {tag(conf)}</div>', unsafe_allow_html=True)
                                sel = st.selectbox(fn, opts, index=di, key=f"{i}_{fn}", label_visibility="collapsed")
                                if sel == "custom...":
                                    st.text_input("custom", key=f"{i}_{fn}_custom", label_visibility="collapsed", placeholder="Type value...")
                        else:
                            # Still need to store values in session state for filename assembly
                            for field in ok_fields:
                                fn = field["name"]
                                fd = result.get(fn, {"value": "x", "confidence": "high"})
                                ai_val = fd.get("value", "x") if isinstance(fd, dict) else str(fd)
                                # Set session state directly without rendering a widget
                                if f"{i}_{fn}" not in st.session_state:
                                    st.session_state[f"{i}_{fn}"] = ai_val

        else:
            # Green rows: store values in session state silently
            for field in config["fields"]:
                fn = field["name"]
                fd = result.get(fn, {"value": "x", "confidence": "high"})
                ai_val = fd.get("value", "x") if isinstance(fd, dict) else str(fd)
                if f"{i}_{fn}" not in st.session_state:
                    st.session_state[f"{i}_{fn}"] = ai_val

    # ── Bulk Edit Panel ──
    sel_set = st.session_state.get("selected_for_rename", set())
    total_selected = len(sel_set)

    if total_selected >= 2:
        st.markdown("---")
        st.markdown(
            f'<div class="section-label">Bulk Edit — {total_selected} files selected</div>',
            unsafe_allow_html=True,
        )

        # Let user pick which fields to bulk-edit
        field_names = [f["display_name"] for f in config["fields"]]
        field_map = {f["display_name"]: f for f in config["fields"]}
        chosen_fields = st.multiselect(
            "Fields to change", field_names,
            key="bulk_fields", placeholder="Pick fields to edit...",
        )

        bulk_values = {}
        if chosen_fields:
            cols = st.columns(min(len(chosen_fields), 3))
            for ci, display_name in enumerate(chosen_fields):
                field = field_map[display_name]
                fn = field["name"]
                with cols[ci % min(len(chosen_fields), 3)]:
                    opts = get_field_options(field)
                    if not opts:
                        opts = ["x"]
                    st.markdown(f'<div class="flabel">{display_name}</div>', unsafe_allow_html=True)
                    val = st.selectbox(
                        fn, opts, key=f"bulk_{fn}", label_visibility="collapsed",
                    )
                    if val == "custom...":
                        val = st.text_input(
                            "custom", key=f"bulk_{fn}_custom",
                            label_visibility="collapsed", placeholder="Type value...",
                        )
                    bulk_values[fn] = val

            if st.button(f"Apply to {total_selected} files", type="primary"):
                for idx in sel_set:
                    for fn, val in bulk_values.items():
                        st.session_state[f"{idx}_{fn}"] = val
                        # Also update scan_results so status/issues refresh
                        if idx in results and fn in results[idx]:
                            if isinstance(results[idx][fn], dict):
                                results[idx][fn]["value"] = val
                                results[idx][fn]["confidence"] = "high"
                                results[idx][fn]["matched_via"] = "manual"
                st.success(f"Updated {len(bulk_values)} field(s) across {total_selected} files.")
                st.rerun()

    # ── Batch Actions Bar ──
    st.markdown("---")

    act1, act2, act3 = st.columns([1.5, 1, 1.5])
    with act1:
        c_all, c_none = st.columns(2)
        with c_all:
            if st.button(f"Select All ({n})", use_container_width=True):
                st.session_state["selected_for_rename"] = set(range(n))
                # Clear checkbox widget keys so they re-initialize from value=
                for j in range(n):
                    st.session_state.pop(f"cb_{j}", None)
                st.rerun()
        with c_none:
            if st.button("Clear", use_container_width=True):
                st.session_state["selected_for_rename"] = set()
                for j in range(n):
                    st.session_state.pop(f"cb_{j}", None)
                st.rerun()

    with act2:
        st.markdown(
            f'<div style="text-align:center;padding:8px;font-size:14px;font-weight:600;color:#37352f;">'
            f'{total_selected} of {n} selected</div>',
            unsafe_allow_html=True,
        )

    with act3:
        c_back, c_rename = st.columns(2)
        with c_back:
            if st.button("← Back", use_container_width=True):
                st.session_state["screen"] = "upload"
                st.rerun()
        with c_rename:
            if st.button("Rename Selected →", type="primary", use_container_width=True,
                         disabled=total_selected == 0):
                st.session_state["screen"] = "confirm"
                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# SCREEN 3: CONFIRM & RENAME
# ══════════════════════════════════════════════════════════════════════════════

def screen_confirm():
    temps = st.session_state["temp_paths"]
    files = st.session_state["uploaded_files_data"]
    selected = st.session_state.get("selected_for_rename", set())
    indices = sorted(selected)
    n = len(indices)

    if n == 0:
        st.warning("No files selected.")
        if st.button("Back"):
            st.session_state["screen"] = "dashboard"
            st.rerun()
        return

    st.markdown('<p class="page-title">Confirm & Rename</p>', unsafe_allow_html=True)
    st.markdown(f'<p class="page-sub">{n} files ready to rename</p>', unsafe_allow_html=True)

    # Stems for dedup logic, then re-attach original extensions for saving
    stems = detect_conflicts([build_filename(i) for i in indices])
    final_names = [stems[j] + Path(temps[indices[j]]).suffix.lower() for j in range(n)]

    rows = "".join(
        f'<tr>'
        f'<td class="o">{Path(files[indices[j]]["name"]).stem}</td>'
        f'<td class="a">→</td>'
        f'<td class="n">{stems[j]}</td>'
        f'<td style="color:#b0b0b0;font-family:monospace;font-size:11px;padding:8px 4px;">'
        f'{Path(temps[indices[j]]).suffix.lower()}</td>'
        f'</tr>'
        for j in range(n)
    )
    st.markdown(f'<table class="rt">{rows}</table>', unsafe_allow_html=True)

    if len(stems) != len(set(stems)):
        st.warning("Duplicate names — suffixes added automatically.")

    st.markdown("")

    # ── Output destination ────────────────────────────────────────────────────
    on_cloud = is_streamlit_cloud()

    if not on_cloud:
        st.markdown(
            '<p style="font-size:13px;font-weight:600;color:#6b7280;letter-spacing:.05em;'
            'text-transform:uppercase;margin:16px 0 8px;">Output folder</p>',
            unsafe_allow_html=True,
        )

        default_dir = st.session_state.get("output_dir_chosen", str(Path.home() / "Desktop"))

        # Quick-pick shortcuts
        qc1, qc2, qc3, qc4 = st.columns(4)
        with qc1:
            if st.button("🖥 Desktop", use_container_width=True):
                st.session_state["output_dir_chosen"] = str(Path.home() / "Desktop")
                st.rerun()
        with qc2:
            if st.button("📥 Downloads", use_container_width=True):
                st.session_state["output_dir_chosen"] = str(Path.home() / "Downloads")
                st.rerun()
        with qc3:
            if st.button("📁 Browse...", use_container_width=True):
                chosen = pick_folder_dialog()
                if chosen:
                    st.session_state["output_dir_chosen"] = chosen
                st.rerun()
        with qc4:
            if st.button("📂 App folder", use_container_width=True):
                st.session_state["output_dir_chosen"] = str(Path(__file__).parent / "renamed")
                st.rerun()

        out_dir = st.text_input(
            "Path",
            value=st.session_state.get("output_dir_chosen", default_dir),
            key="output_dir_text",
            label_visibility="collapsed",
        )
        # Keep session state in sync if user types manually
        if out_dir != st.session_state.get("output_dir_chosen"):
            st.session_state["output_dir_chosen"] = out_dir

        # Validate path
        p = Path(out_dir)
        if p.exists():
            st.markdown(
                f'<p style="font-size:12px;color:#16a34a;margin-top:2px;">✓ Folder exists — files will be saved here</p>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<p style="font-size:12px;color:#d97706;margin-top:2px;">⚠ Folder doesn\'t exist yet — will be created</p>',
                unsafe_allow_html=True,
            )
    else:
        out_dir = str(Path(__file__).parent / "renamed")
        st.info("Running on Streamlit Cloud — files will be available as a ZIP download.")

    st.markdown("")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("← Back to Dashboard", use_container_width=True):
            st.session_state["screen"] = "dashboard"
            st.rerun()
    with c2:
        if st.button(f"Rename & Save {n} Files", type="primary", use_container_width=True):
            os.makedirs(out_dir, exist_ok=True)
            prog = st.progress(0)
            for j, idx in enumerate(indices):
                prog.progress(int(((j + 1) / n) * 100), text=f"{j+1}/{n}")
                shutil.copy2(temps[idx], os.path.join(out_dir, final_names[j]))
            prog.progress(100, text="Done!")
            st.session_state.update({"rename_done": True, "output_dir": out_dir})
            st.rerun()

    if st.session_state.get("rename_done"):
        d = st.session_state.get("output_dir", out_dir)

        if on_cloud:
            # Cloud: offer ZIP download
            import io, zipfile
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for j, idx in enumerate(indices):
                    zf.write(os.path.join(d, final_names[j]), arcname=final_names[j])
            buf.seek(0)
            st.success(f"✅ Done! Download your {n} renamed files below.")
            st.download_button(
                "⬇️ Download ZIP",
                data=buf,
                file_name="renamed_creatives.zip",
                mime="application/zip",
                type="primary",
                use_container_width=True,
            )
        else:
            st.success(f"✅ Done! {n} files saved to `{d}`")

        # Check for custom values to add to library
        new_vals = collect_custom_values()
        if new_vals:
            st.markdown("---")
            st.markdown(f"**You used {len(new_vals)} new value(s) not in the library.** Add them?")
            for nv in new_vals:
                st.markdown(f"- `{nv['field']}`: **{nv['value']}**")
            if st.button("Add to Library", type="primary"):
                for nv in new_vals:
                    library.add_value(nv["field"], nv["value"])
                st.success("Added! Future scans will include these values.")

        c1, c2 = st.columns(2)
        with c1:
            if not on_cloud and st.button("📂 Open Folder", type="primary", use_container_width=True):
                open_folder(d)
        with c2:
            if st.button("🔄 Start Over", use_container_width=True):
                for k in list(st.session_state.keys()):
                    del st.session_state[k]
                st.rerun()


# ── Router ───────────────────────────────────────────────────────────────────
{
    "upload": screen_upload,
    "dashboard": screen_dashboard,
    "review": screen_dashboard,  # Backward compat if session has old value
    "confirm": screen_confirm,
}[st.session_state.get("screen", "upload")]()
