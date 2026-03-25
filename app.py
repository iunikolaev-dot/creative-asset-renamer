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

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent))

load_dotenv()

from core.config import load_config
from core.vision import analyze_file
from core.namer import assemble_name, detect_conflicts
from core.scanner import extract_video_frame

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="Creative Asset Renamer", page_icon="🎨", layout="wide")

# ── Load config ──────────────────────────────────────────────────────────────
config = load_config()

# ── Session state defaults ───────────────────────────────────────────────────
defaults = {
    "screen": "upload",
    "scan_results": {},
    "uploaded_files_data": [],
    "uploaded_files_bytes": {},
    "temp_paths": [],
    "selected_file_idx": 0,
    "versions": {},
    "rename_done": False,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Global */
    .block-container { padding-top: 2rem; }

    /* File list card */
    .file-card {
        padding: 10px 14px;
        border-radius: 10px;
        margin-bottom: 6px;
        cursor: pointer;
        font-size: 13px;
        border: 1px solid #e2e8f0;
        background: #ffffff;
        transition: all 0.15s;
    }
    .file-card:hover { background: #f1f5f9; }
    .file-card-active {
        background: #eef2ff !important;
        border-color: #6366f1 !important;
        box-shadow: 0 0 0 1px #6366f1;
    }
    .file-card-name {
        font-weight: 500;
        color: #1e293b;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    /* Filename preview */
    .filename-preview {
        background: linear-gradient(135deg, #eef2ff 0%, #e0e7ff 100%);
        border: 1px solid #c7d2fe;
        border-radius: 10px;
        padding: 14px 18px;
        font-family: 'SF Mono', 'Fira Code', 'Courier New', monospace;
        font-size: 13px;
        color: #312e81;
        word-break: break-all;
        margin: 8px 0;
        letter-spacing: 0.3px;
    }

    /* Confidence badges */
    .badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 20px;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.3px;
    }
    .badge-high { background: #dcfce7; color: #166534; }
    .badge-medium { background: #fef9c3; color: #854d0e; }
    .badge-low { background: #fee2e2; color: #991b1b; }
    .badge-auto { background: #f1f5f9; color: #475569; }
    .badge-manual { background: #f1f5f9; color: #475569; }

    /* Upload badge */
    .upload-badge {
        background: #6366f1;
        color: white;
        padding: 4px 14px;
        border-radius: 20px;
        font-size: 13px;
        font-weight: 500;
        display: inline-block;
    }

    /* Section headers */
    .section-header {
        font-size: 12px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        color: #94a3b8;
        margin-bottom: 8px;
        padding-bottom: 6px;
        border-bottom: 1px solid #f1f5f9;
    }

    /* Rename table */
    .rename-row {
        display: flex;
        align-items: center;
        padding: 10px 14px;
        border-radius: 8px;
        margin-bottom: 4px;
        font-size: 13px;
    }
    .rename-row:nth-child(odd) { background: #f8fafc; }
    .rename-arrow { color: #6366f1; font-weight: bold; margin: 0 12px; }

    /* Version buttons */
    div[data-testid="stButton"] > button {
        border-radius: 8px;
    }

    /* Hide streamlit branding */
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ──────────────────────────────────────────────────────────────────

def save_temp_file(uploaded_file) -> str:
    temp_dir = tempfile.mkdtemp()
    temp_path = os.path.join(temp_dir, uploaded_file.name)
    with open(temp_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return temp_path


def show_preview(file_path: str, file_idx: int):
    """Show image or video preview. Uses st.video for videos (works without ffmpeg)."""
    ext = Path(file_path).suffix.lower()
    if ext in (".jpg", ".jpeg", ".png"):
        try:
            img = Image.open(file_path)
            st.image(img, use_container_width=True)
        except Exception:
            st.info("Could not load image preview")
    elif ext in (".mp4", ".mov", ".webm"):
        # Use raw bytes for st.video — works on Streamlit Cloud without ffmpeg
        file_bytes = st.session_state["uploaded_files_bytes"].get(file_idx)
        if file_bytes:
            st.video(file_bytes)
        else:
            try:
                with open(file_path, "rb") as f:
                    st.video(f.read())
            except Exception:
                st.info("Could not load video preview")


def confidence_badge(confidence: str) -> str:
    css_class = {
        "high": "badge-high",
        "medium": "badge-medium",
        "low": "badge-low",
        "auto": "badge-auto",
        "manual": "badge-manual",
        "failed": "badge-low",
    }.get(confidence, "badge-low")
    label = confidence.capitalize()
    return f'<span class="badge {css_class}">{label}</span>'


def build_filename_for_file(file_idx: int) -> str:
    result = {}
    for field in config["fields"]:
        key = f"{file_idx}_{field['name']}"
        if key in st.session_state:
            val = st.session_state[key]
            if val == "custom...":
                custom_key = f"{file_idx}_{field['name']}_custom"
                val = st.session_state.get(custom_key, "x")
            result[field["name"]] = {"value": val, "confidence": "user"}
        else:
            scan = st.session_state["scan_results"].get(file_idx, {})
            field_data = scan.get(field["name"], {"value": "x", "confidence": "low"})
            result[field["name"]] = field_data

    version = st.session_state["versions"].get(file_idx, None)
    original_ext = Path(st.session_state["temp_paths"][file_idx]).suffix
    return assemble_name(result, config, version=version, original_extension=original_ext)


def open_folder(path: str):
    system = platform.system()
    if system == "Darwin":
        subprocess.Popen(["open", path])
    elif system == "Windows":
        subprocess.Popen(["explorer", path])
    else:
        subprocess.Popen(["xdg-open", path])


# ══════════════════════════════════════════════════════════════════════════════
# SCREEN 1: UPLOAD
# ══════════════════════════════════════════════════════════════════════════════

def screen_upload():
    # Centered layout
    spacer1, center, spacer2 = st.columns([1, 2, 1])

    with center:
        st.markdown("")
        st.markdown("## 🎨 Creative Asset Renamer")
        st.caption("Drop your creatives, get structured names powered by AI")
        st.markdown("")

        uploaded_files = st.file_uploader(
            "Upload your ad creatives",
            type=["jpg", "jpeg", "png", "mp4", "mov", "webm"],
            accept_multiple_files=True,
            key="file_uploader",
        )

        if uploaded_files:
            st.markdown(f'<span class="upload-badge">{len(uploaded_files)} file{"s" if len(uploaded_files) != 1 else ""} selected</span>', unsafe_allow_html=True)
            st.markdown("")

        # Who Made It
        who_options = []
        for field in config["fields"]:
            if field["name"] == "who_made_it":
                who_options = field["allowed_values"] + ["custom..."]
                break

        who_made_it = st.selectbox("Who Made It (applies to all files)", who_options, key="who_made_it_global")

        if who_made_it == "custom...":
            who_made_it = st.text_input("Enter creator name", key="who_made_it_custom")

        st.markdown("")

        scan_disabled = not uploaded_files
        if st.button("Scan Files with AI", disabled=scan_disabled, type="primary", use_container_width=True):
            temp_paths = []
            file_bytes_map = {}
            progress = st.progress(0, text="Preparing files...")

            for i, uf in enumerate(uploaded_files):
                progress.progress((i * 0.3) / len(uploaded_files), text=f"Saving file {i+1} of {len(uploaded_files)}...")
                temp_paths.append(save_temp_file(uf))
                # Store raw bytes for video preview
                file_bytes_map[i] = uf.getvalue()

            st.session_state["temp_paths"] = temp_paths
            st.session_state["uploaded_files_bytes"] = file_bytes_map
            st.session_state["uploaded_files_data"] = [
                {"name": uf.name, "size": uf.size} for uf in uploaded_files
            ]

            results = {}
            for i, temp_path in enumerate(temp_paths):
                progress.progress(
                    0.3 + (i / len(temp_paths)) * 0.7,
                    text=f"Scanning file {i+1} of {len(temp_paths)}: {uploaded_files[i].name}",
                )
                results[i] = analyze_file(temp_path, config, who_made_it)

            progress.progress(1.0, text="Scan complete!")

            st.session_state["scan_results"] = results
            st.session_state["versions"] = {i: None for i in range(len(temp_paths))}
            st.session_state["screen"] = "review"
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# SCREEN 2: REVIEW & EDIT
# ══════════════════════════════════════════════════════════════════════════════

def screen_review():
    results = st.session_state["scan_results"]
    temp_paths = st.session_state["temp_paths"]
    files_data = st.session_state["uploaded_files_data"]
    num_files = len(temp_paths)

    if num_files == 0:
        st.warning("No files scanned. Go back to upload.")
        if st.button("Back to Upload"):
            st.session_state["screen"] = "upload"
            st.rerun()
        return

    idx = st.session_state["selected_file_idx"]
    if idx >= num_files:
        idx = 0
        st.session_state["selected_file_idx"] = 0

    # ── Three-column layout ──
    file_col, preview_col, fields_col = st.columns([1.2, 1.5, 2.3], gap="medium")

    # ── Column 1: File list ──
    with file_col:
        st.markdown('<div class="section-header">Files</div>', unsafe_allow_html=True)

        for i in range(num_files):
            fname = files_data[i]["name"]
            is_selected = (i == idx)
            ext = Path(fname).suffix.lower()
            icon = "🖼" if ext in (".jpg", ".jpeg", ".png") else "🎬"

            btn_type = "primary" if is_selected else "secondary"
            if st.button(f"{icon}  {fname}", key=f"file_btn_{i}", use_container_width=True, type=btn_type):
                st.session_state["selected_file_idx"] = i
                st.rerun()

        st.markdown("")

        # Apply to All
        if st.button("Apply shared fields to all", use_container_width=True, help="Applies Language, Who Made It & Details from current file to all"):
            batch_fields = ["language", "who_made_it", "details"]
            for field_name in batch_fields:
                source_key = f"{idx}_{field_name}"
                if source_key in st.session_state:
                    for j in range(num_files):
                        if j != idx:
                            st.session_state[f"{j}_{field_name}"] = st.session_state[source_key]
            st.rerun()

        st.markdown("---")

        # Navigation
        if st.button("Back to Upload", use_container_width=True):
            st.session_state["screen"] = "upload"
            st.rerun()

        if st.button("Continue to Rename", type="primary", use_container_width=True):
            st.session_state["screen"] = "confirm"
            st.rerun()

    # ── Column 2: Preview ──
    with preview_col:
        st.markdown('<div class="section-header">Preview</div>', unsafe_allow_html=True)

        file_path = temp_paths[idx]
        file_data = files_data[idx]
        scan_result = results.get(idx, {})

        show_preview(file_path, idx)

        st.caption(f"**{file_data['name']}**")
        provider = scan_result.get("_provider", "unknown")
        st.caption(f"AI: {provider}")

        # Live filename preview
        st.markdown("")
        st.markdown('<div class="section-header">Generated Filename</div>', unsafe_allow_html=True)
        preview_name = build_filename_for_file(idx)
        st.markdown(f'<div class="filename-preview">{preview_name}</div>', unsafe_allow_html=True)

        # Version controls
        ver_col1, ver_col2, ver_col3 = st.columns([2, 1, 1])
        with ver_col1:
            current_ver = st.session_state["versions"].get(idx)
            ver_text = f"v{current_ver}" if current_ver and current_ver > 1 else "No version"
            st.caption(ver_text)
        with ver_col2:
            if st.button("+", key=f"ver_up_{idx}", help="Add version"):
                cur = st.session_state["versions"].get(idx) or 1
                st.session_state["versions"][idx] = cur + 1
                st.rerun()
        with ver_col3:
            if st.button("−", key=f"ver_down_{idx}", help="Remove version"):
                cur = st.session_state["versions"].get(idx)
                if cur and cur > 1:
                    st.session_state["versions"][idx] = cur - 1
                else:
                    st.session_state["versions"][idx] = None
                st.rerun()

    # ── Column 3: Field editors ──
    with fields_col:
        st.markdown('<div class="section-header">Fields</div>', unsafe_allow_html=True)
        scan_result = results.get(idx, {})

        for field in config["fields"]:
            field_name = field["name"]
            field_data = scan_result.get(field_name, {"value": "x", "confidence": "low"})

            ai_value = field_data.get("value", "x") if isinstance(field_data, dict) else str(field_data)
            confidence = field_data.get("confidence", "low") if isinstance(field_data, dict) else "low"

            allowed = field.get("allowed_values", [])
            options = list(allowed)
            if field.get("allow_custom", False):
                options.append("custom...")

            # Determine default index
            if ai_value in options:
                default_idx = options.index(ai_value)
            else:
                if ai_value and ai_value != "x":
                    options.insert(0, ai_value)
                    default_idx = 0
                else:
                    default_idx = 0

            label_col, select_col = st.columns([1, 3])

            with label_col:
                st.markdown(f"**{field['display_name']}**")
                st.markdown(confidence_badge(confidence), unsafe_allow_html=True)

            with select_col:
                key = f"{idx}_{field_name}"
                selected = st.selectbox(
                    field["display_name"],
                    options,
                    index=default_idx,
                    key=key,
                    label_visibility="collapsed",
                )

                if selected == "custom...":
                    custom_key = f"{idx}_{field_name}_custom"
                    st.text_input(
                        f"Custom {field['display_name']}",
                        key=custom_key,
                        label_visibility="collapsed",
                        placeholder=f"Enter custom value...",
                    )


# ══════════════════════════════════════════════════════════════════════════════
# SCREEN 3: CONFIRM & RENAME
# ══════════════════════════════════════════════════════════════════════════════

def screen_confirm():
    temp_paths = st.session_state["temp_paths"]
    files_data = st.session_state["uploaded_files_data"]
    num_files = len(temp_paths)

    if num_files == 0:
        st.warning("No files to rename.")
        if st.button("Back to Upload"):
            st.session_state["screen"] = "upload"
            st.rerun()
        return

    spacer1, center, spacer2 = st.columns([1, 3, 1])

    with center:
        st.markdown("## Confirm & Rename")
        st.caption(f"{num_files} files ready to rename")
        st.markdown("")

        # Build all new names
        new_names = [build_filename_for_file(i) for i in range(num_files)]
        new_names = detect_conflicts(new_names)

        # Rename preview table
        st.markdown('<div class="section-header">Rename Preview</div>', unsafe_allow_html=True)

        for i in range(num_files):
            col_old, col_arrow, col_new = st.columns([3, 0.5, 4])
            with col_old:
                st.code(files_data[i]["name"], language=None)
            with col_arrow:
                st.markdown("→")
            with col_new:
                st.code(new_names[i], language=None)

        # Conflict check
        name_counts = {}
        for n in new_names:
            name_counts[n] = name_counts.get(n, 0) + 1
        has_conflicts = any(c > 1 for c in name_counts.values())
        if has_conflicts:
            st.warning("Some files had duplicate names. Suffixes (_a, _b) were added.")

        st.markdown("")

        # Output mode
        output_mode = st.radio(
            "Output mode",
            ["Copy to output folder (recommended)", "Rename in place"],
            index=0,
            key="output_mode",
        )

        output_dir = str(Path(__file__).parent / "renamed")
        if output_mode == "Copy to output folder (recommended)":
            output_dir = st.text_input("Output folder", value=output_dir, key="output_dir")

        st.markdown("")

        # Buttons
        btn_col1, btn_col2 = st.columns(2)
        with btn_col1:
            if st.button("Back to Review", use_container_width=True):
                st.session_state["screen"] = "review"
                st.rerun()
        with btn_col2:
            if st.button("Rename All", type="primary", use_container_width=True):
                os.makedirs(output_dir, exist_ok=True)
                progress = st.progress(0, text="Renaming files...")
                success_count = 0

                for i in range(num_files):
                    progress.progress((i + 1) / num_files, text=f"Renaming {i+1} of {num_files}...")
                    src = temp_paths[i]
                    new_name = new_names[i]

                    try:
                        if output_mode == "Copy to output folder (recommended)":
                            dst = os.path.join(output_dir, new_name)
                        else:
                            dst = os.path.join(os.path.dirname(src), new_name)
                        shutil.copy2(src, dst)
                        success_count += 1
                    except Exception as e:
                        st.error(f"Failed: {files_data[i]['name']} — {e}")

                progress.progress(1.0, text="Done!")
                st.session_state["rename_done"] = True
                st.session_state["output_dir"] = output_dir
                st.rerun()

        # After rename success
        if st.session_state.get("rename_done"):
            final_dir = st.session_state.get("output_dir", output_dir)
            st.markdown("")
            st.success(f"All files renamed successfully! Saved to: `{final_dir}`")

            done_col1, done_col2 = st.columns(2)
            with done_col1:
                if st.button("Open Output Folder", type="primary", use_container_width=True):
                    open_folder(final_dir)
            with done_col2:
                if st.button("Start Over", use_container_width=True):
                    for key in list(st.session_state.keys()):
                        del st.session_state[key]
                    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# ROUTER
# ══════════════════════════════════════════════════════════════════════════════

screen = st.session_state.get("screen", "upload")

if screen == "upload":
    screen_upload()
elif screen == "review":
    screen_review()
elif screen == "confirm":
    screen_confirm()
