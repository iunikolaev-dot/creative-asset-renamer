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
    ext = Path(st.session_state["temp_paths"][file_idx]).suffix
    return assemble_name(result, config, version=ver, original_extension=ext)


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
        st.markdown('<p class="hero-sub">Drop up to 100 creatives. AI names them. You review exceptions.</p>', unsafe_allow_html=True)

        uploaded_files = st.file_uploader(
            "Upload", type=["jpg", "jpeg", "png", "mp4", "mov", "webm"],
            accept_multiple_files=True, key="file_uploader", label_visibility="collapsed",
        )
        if uploaded_files:
            st.markdown(f'<span class="pill">{len(uploaded_files)} file{"s" if len(uploaded_files) != 1 else ""}</span>', unsafe_allow_html=True)

        st.markdown("")
        who_opts = library.get_values("who_made_it") + ["custom..."]
        who = st.selectbox("Who Made It (applies to all files)", who_opts, key="who_made_it_global")
        if who == "custom...":
            who = st.text_input("Creator name", key="who_made_it_custom")

        st.markdown("")
        n = len(uploaded_files) if uploaded_files else 0
        btn_label = f"Scan {n} files with AI" if n > 0 else "Scan Files with AI"
        if st.button(btn_label, disabled=not uploaded_files, type="primary", use_container_width=True):
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
            })

            results = {}
            statuses = {"ready": [], "needs_review": [], "failed": []}
            for i, tp in enumerate(temps):
                pct = 20 + int((i / len(temps)) * 80)
                prog.progress(pct, text=f"Scanning {i+1}/{len(temps)}: {uploaded_files[i].name}")
                result = analyze_file(tp, config, who, library)
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

    # ── Summary Stats Bar ──
    n_ready = len(statuses.get("ready", []))
    n_review = len(statuses.get("needs_review", []))
    n_failed = len(statuses.get("failed", []))

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(f'<div class="stat-card stat-ready"><h2>{n_ready}</h2><p>Ready</p></div>', unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div class="stat-card stat-review"><h2>{n_review}</h2><p>Needs Review</p></div>', unsafe_allow_html=True)
    with c3:
        st.markdown(f'<div class="stat-card stat-failed"><h2>{n_failed}</h2><p>Failed</p></div>', unsafe_allow_html=True)

    st.markdown("")

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

    # ── Batch Table ──
    for i in visible_files:
        result = results[i]
        status = classify_file_status(result)
        issues = get_issues(result)
        new_name = build_filename(i)

        dot = status_dot(status)
        issues_html = " ".join(f'<span class="issue-tag">{iss}</span>' for iss in issues) if issues else ""

        # Row header
        st.markdown(
            f'<div class="file-row">'
            f'{dot}'
            f'<span class="fname" title="{files[i]["name"]}">{files[i]["name"]}</span>'
            f'<span class="arrow">→</span>'
            f'<span class="new-name" title="{new_name}">{new_name}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        if issues_html:
            st.markdown(f'<div style="margin: -4px 0 6px 26px;">{issues_html}</div>', unsafe_allow_html=True)

        # Inline editor — expander for yellow/red rows
        if status in ("needs_review", "failed"):
            with st.expander(f"Edit fields for {files[i]['name']}", expanded=False):
                col_thumb, col_fields = st.columns([1, 2.5])

                with col_thumb:
                    thumb = get_thumbnail(temps[i])
                    if thumb:
                        st.image(thumb, width=180)
                    else:
                        fb = st.session_state["uploaded_files_bytes"].get(i)
                        if fb:
                            st.video(fb)

                with col_fields:
                    for field in config["fields"]:
                        fn = field["name"]
                        fd = result.get(fn, {"value": "x", "confidence": "low"})
                        ai_val = fd.get("value", "x") if isinstance(fd, dict) else str(fd)
                        conf = fd.get("confidence", "low") if isinstance(fd, dict) else "low"
                        ai_raw = fd.get("ai_raw", "") if isinstance(fd, dict) else ""
                        matched_via = fd.get("matched_via", "") if isinstance(fd, dict) else ""

                        # Only show problematic fields expanded
                        is_problem = conf == "low" or matched_via == "unmatched"

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

                        if is_problem:
                            hint = f" (AI raw: {ai_raw})" if ai_raw and ai_raw != ai_val else ""
                            st.markdown(f'<div class="flabel">{field["display_name"]} {tag(conf)}{hint}</div>', unsafe_allow_html=True)
                            sel = st.selectbox(fn, opts, index=di, key=f"{i}_{fn}", label_visibility="collapsed")
                            if sel == "custom...":
                                st.text_input("custom", key=f"{i}_{fn}_custom", label_visibility="collapsed", placeholder="Type value...")
                        else:
                            # Non-problematic: compact display
                            st.markdown(
                                f'<div class="flabel">{field["display_name"]} {tag(conf)}'
                                f' <span style="font-weight:400;color:#787774;">= {ai_val}</span></div>',
                                unsafe_allow_html=True,
                            )
                            # Hidden selectbox to store value
                            st.selectbox(fn, opts, index=di, key=f"{i}_{fn}", label_visibility="collapsed")

    # ── Batch Actions Bar ──
    st.markdown("---")
    sel = st.session_state.get("selected_for_rename", set())

    act1, act2, act3 = st.columns([1.5, 1, 1.5])
    with act1:
        select_all = st.checkbox(
            f"Select all Ready ({n_ready} files)",
            value=len(sel) >= n_ready and n_ready > 0,
            key="select_all_ready",
        )
        if select_all:
            st.session_state["selected_for_rename"] = set(range(n))  # Select all
        else:
            st.session_state["selected_for_rename"] = set()

    with act2:
        total_selected = len(st.session_state.get("selected_for_rename", set()))
        st.markdown(f'<div style="text-align:center;padding:8px;font-size:14px;font-weight:600;color:#37352f;">{total_selected} files selected</div>', unsafe_allow_html=True)

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

    names = detect_conflicts([build_filename(i) for i in indices])

    rows = "".join(
        f'<tr><td class="o">{files[indices[j]]["name"]}</td>'
        f'<td class="a">→</td>'
        f'<td class="n">{names[j]}</td></tr>'
        for j in range(n)
    )
    st.markdown(f'<table class="rt">{rows}</table>', unsafe_allow_html=True)

    if len(names) != len(set(names)):
        st.warning("Duplicate names — suffixes added automatically.")

    st.markdown("")
    mode = st.radio("Output", ["Copy to output folder (recommended)", "Rename in place"], index=0, key="output_mode")
    out_dir = str(Path(__file__).parent / "renamed")
    if "Copy" in mode:
        out_dir = st.text_input("Output folder", value=out_dir, key="output_dir")

    st.markdown("")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("← Back to Dashboard", use_container_width=True):
            st.session_state["screen"] = "dashboard"
            st.rerun()
    with c2:
        if st.button(f"Rename All {n} Files", type="primary", use_container_width=True):
            os.makedirs(out_dir, exist_ok=True)
            prog = st.progress(0)
            for j, idx in enumerate(indices):
                prog.progress(int(((j + 1) / n) * 100), text=f"{j+1}/{n}")
                shutil.copy2(temps[idx], os.path.join(out_dir, names[j]))
            prog.progress(100, text="Done!")
            st.session_state.update({"rename_done": True, "output_dir": out_dir})
            st.rerun()

    if st.session_state.get("rename_done"):
        d = st.session_state.get("output_dir", out_dir)
        st.success(f"Done! {n} files renamed in `{d}`")

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
            if st.button("📂 Open Folder", type="primary", use_container_width=True):
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
