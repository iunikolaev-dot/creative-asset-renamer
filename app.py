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
st.set_page_config(page_title="Creative Asset Renamer", layout="wide")

# ── Load config ──────────────────────────────────────────────────────────────
@st.cache_data
def get_config():
    return load_config()

config = get_config()

# ── Session state defaults ───────────────────────────────────────────────────
if "screen" not in st.session_state:
    st.session_state["screen"] = "upload"
if "scan_results" not in st.session_state:
    st.session_state["scan_results"] = {}
if "uploaded_files_data" not in st.session_state:
    st.session_state["uploaded_files_data"] = []
if "temp_paths" not in st.session_state:
    st.session_state["temp_paths"] = []
if "selected_file_idx" not in st.session_state:
    st.session_state["selected_file_idx"] = 0
if "versions" not in st.session_state:
    st.session_state["versions"] = {}
if "rename_done" not in st.session_state:
    st.session_state["rename_done"] = False

# ── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .filename-preview {
        background-color: #e8f4f8;
        border: 1px solid #b8d4e3;
        border-radius: 8px;
        padding: 12px 16px;
        font-family: 'Courier New', monospace;
        font-size: 14px;
        color: #1a3a4a;
        word-break: break-all;
        margin: 8px 0;
    }
    .confidence-high { color: #22c55e; font-weight: bold; }
    .confidence-medium { color: #eab308; font-weight: bold; }
    .confidence-low { color: #ef4444; font-weight: bold; }
    .confidence-auto, .confidence-manual { color: #9ca3af; font-weight: bold; }
    .file-badge {
        background: #6366f1;
        color: white;
        padding: 4px 12px;
        border-radius: 12px;
        font-size: 14px;
        display: inline-block;
    }
    .status-reviewed { color: #22c55e; }
    .status-pending { color: #eab308; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ──────────────────────────────────────────────────────────────────

def save_temp_file(uploaded_file) -> str:
    temp_dir = tempfile.mkdtemp()
    temp_path = os.path.join(temp_dir, uploaded_file.name)
    with open(temp_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return temp_path


def get_thumbnail(file_path: str, max_size: int = 400) -> Image.Image | None:
    ext = Path(file_path).suffix.lower()
    try:
        if ext in (".jpg", ".jpeg", ".png"):
            img = Image.open(file_path)
            img.thumbnail((max_size, max_size))
            return img
        elif ext in (".mp4", ".mov", ".webm"):
            frame_bytes = extract_video_frame(file_path, 0.25)
            if frame_bytes:
                import io
                img = Image.open(io.BytesIO(frame_bytes))
                img.thumbnail((max_size, max_size))
                return img
    except Exception:
        pass
    return None


def confidence_badge(confidence: str) -> str:
    icons = {
        "high": '<span class="confidence-high">● High</span>',
        "medium": '<span class="confidence-medium">● Medium</span>',
        "low": '<span class="confidence-low">● Low</span>',
        "auto": '<span class="confidence-auto">● Auto</span>',
        "manual": '<span class="confidence-manual">● Manual</span>',
        "failed": '<span class="confidence-low">● Failed</span>',
    }
    return icons.get(confidence, icons["low"])


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
    st.markdown("# Creative Asset Renamer")
    st.markdown("*Drop your creatives, get structured names*")
    st.markdown("---")

    uploaded_files = st.file_uploader(
        "Upload your ad creatives",
        type=["jpg", "jpeg", "png", "mp4", "mov", "webm"],
        accept_multiple_files=True,
        key="file_uploader",
    )

    if uploaded_files:
        st.markdown(f'<span class="file-badge">{len(uploaded_files)} files selected</span>', unsafe_allow_html=True)

    st.markdown("---")

    # Who Made It — persists across all files
    who_options = []
    for field in config["fields"]:
        if field["name"] == "who_made_it":
            who_options = field["allowed_values"] + ["custom..."]
            break

    who_made_it = st.selectbox("Who Made It (applies to all files)", who_options, key="who_made_it_global")

    if who_made_it == "custom...":
        who_made_it = st.text_input("Enter creator name", key="who_made_it_custom")

    st.markdown("---")

    # Scan button
    scan_disabled = not uploaded_files
    if st.button("🔍 Scan Files with AI", disabled=scan_disabled, type="primary", use_container_width=True):
        temp_paths = []
        progress = st.progress(0, text="Preparing files...")

        for i, uf in enumerate(uploaded_files):
            progress.progress((i * 0.3) / len(uploaded_files), text=f"Saving file {i+1} of {len(uploaded_files)}...")
            temp_paths.append(save_temp_file(uf))

        st.session_state["temp_paths"] = temp_paths
        st.session_state["uploaded_files_data"] = [
            {"name": uf.name, "size": uf.size} for uf in uploaded_files
        ]

        results = {}
        for i, temp_path in enumerate(temp_paths):
            progress.progress(
                0.3 + (i / len(temp_paths)) * 0.7,
                text=f"🤖 Scanning file {i+1} of {len(temp_paths)}: {uploaded_files[i].name}",
            )
            results[i] = analyze_file(temp_path, config, who_made_it)

        progress.progress(1.0, text="✅ Scan complete!")

        st.session_state["scan_results"] = results
        st.session_state["versions"] = {i: None for i in range(len(temp_paths))}
        st.session_state["screen"] = "review"
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# SCREEN 2: REVIEW & EDIT
# ══════════════════════════════════════════════════════════════════════════════

def screen_review():
    st.markdown("# Review & Edit")

    results = st.session_state["scan_results"]
    temp_paths = st.session_state["temp_paths"]
    files_data = st.session_state["uploaded_files_data"]
    num_files = len(temp_paths)

    if num_files == 0:
        st.warning("No files scanned. Go back to upload.")
        if st.button("← Back to Upload"):
            st.session_state["screen"] = "upload"
            st.rerun()
        return

    # Two-column layout
    left_col, right_col = st.columns([2, 3])

    # ── Left: File list ──
    with left_col:
        st.markdown("### Files")
        for i in range(num_files):
            fname = files_data[i]["name"]
            is_selected = (i == st.session_state["selected_file_idx"])

            # Check if user has modified any field for this file
            reviewed = any(
                f"{i}_{field['name']}" in st.session_state
                for field in config["fields"]
            )
            status = "✅" if reviewed else "🟡"

            btn_label = f"{status} {fname}"
            if st.button(btn_label, key=f"file_btn_{i}", use_container_width=True,
                         type="primary" if is_selected else "secondary"):
                st.session_state["selected_file_idx"] = i
                st.rerun()

    # ── Right: Detail view ──
    with right_col:
        idx = st.session_state["selected_file_idx"]
        if idx >= num_files:
            idx = 0
            st.session_state["selected_file_idx"] = 0

        file_path = temp_paths[idx]
        file_data = files_data[idx]
        scan_result = results.get(idx, {})

        # Thumbnail
        thumb = get_thumbnail(file_path)
        if thumb:
            st.image(thumb, caption=file_data["name"], use_container_width=False)
        else:
            st.info(f"📁 {file_data['name']} (preview not available)")

        st.caption(f"Original: **{file_data['name']}** | Provider: {scan_result.get('_provider', 'unknown')}")

        st.markdown("---")

        # ── Field editors ──
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
                # AI returned a value not in allowed list — add it as first option
                if ai_value and ai_value != "x":
                    options.insert(0, ai_value)
                    default_idx = 0
                else:
                    default_idx = 0

            col_label, col_select, col_badge = st.columns([2, 4, 2])

            with col_label:
                st.markdown(f"**{field['display_name']}**")

            with col_select:
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
                        placeholder=f"Enter custom {field['display_name'].lower()}...",
                    )

            with col_badge:
                # Show badge only if user hasn't overridden
                st.markdown(confidence_badge(confidence), unsafe_allow_html=True)

        # ── Live filename preview ──
        st.markdown("---")
        preview_name = build_filename_for_file(idx)
        st.markdown(f'<div class="filename-preview">📄 {preview_name}</div>', unsafe_allow_html=True)

        # Version selector
        ver_col1, ver_col2, ver_col3 = st.columns([2, 1, 1])
        with ver_col1:
            current_ver = st.session_state["versions"].get(idx)
            st.caption(f"Version: {'None' if not current_ver else f'v{current_ver}'}")
        with ver_col2:
            if st.button("➕ Version", key=f"ver_up_{idx}"):
                cur = st.session_state["versions"].get(idx) or 1
                st.session_state["versions"][idx] = cur + 1
                st.rerun()
        with ver_col3:
            if st.button("➖ Version", key=f"ver_down_{idx}"):
                cur = st.session_state["versions"].get(idx)
                if cur and cur > 1:
                    st.session_state["versions"][idx] = cur - 1
                else:
                    st.session_state["versions"][idx] = None
                st.rerun()

        # Apply to All button
        st.markdown("---")
        if st.button("📋 Apply Language, Who Made It & Details to All Files", use_container_width=True):
            batch_fields = ["language", "who_made_it", "details"]
            for field_name in batch_fields:
                source_key = f"{idx}_{field_name}"
                if source_key in st.session_state:
                    for j in range(num_files):
                        if j != idx:
                            target_key = f"{j}_{field_name}"
                            st.session_state[target_key] = st.session_state[source_key]
            st.success("Applied to all files!")
            st.rerun()

    # Navigation
    st.markdown("---")
    nav_col1, nav_col2 = st.columns(2)
    with nav_col1:
        if st.button("← Back to Upload", use_container_width=True):
            st.session_state["screen"] = "upload"
            st.rerun()
    with nav_col2:
        if st.button("Continue to Rename →", type="primary", use_container_width=True):
            st.session_state["screen"] = "confirm"
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# SCREEN 3: CONFIRM & RENAME
# ══════════════════════════════════════════════════════════════════════════════

def screen_confirm():
    st.markdown("# Confirm & Rename")

    temp_paths = st.session_state["temp_paths"]
    files_data = st.session_state["uploaded_files_data"]
    num_files = len(temp_paths)

    if num_files == 0:
        st.warning("No files to rename.")
        if st.button("← Back to Upload"):
            st.session_state["screen"] = "upload"
            st.rerun()
        return

    # Build all new names
    new_names = [build_filename_for_file(i) for i in range(num_files)]
    new_names = detect_conflicts(new_names)

    # Show table
    has_conflicts = len(new_names) != len(set(new_names))

    st.markdown("### File Rename Preview")
    for i in range(num_files):
        col1, col2 = st.columns(2)
        with col1:
            st.text(files_data[i]["name"])
        with col2:
            st.text(new_names[i])

    if has_conflicts:
        st.warning("⚠️ Some files had duplicate names. Suffixes (_a, _b) were added automatically.")

    st.markdown("---")

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

    st.markdown("---")

    # Navigation + Rename
    nav_col1, nav_col2 = st.columns(2)
    with nav_col1:
        if st.button("← Back to Review", use_container_width=True):
            st.session_state["screen"] = "review"
            st.rerun()

    with nav_col2:
        if st.button("✅ Rename All", type="primary", use_container_width=True):
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
                        shutil.copy2(src, dst)
                    else:
                        src_dir = os.path.dirname(src)
                        dst = os.path.join(src_dir, new_name)
                        shutil.copy2(src, dst)
                    success_count += 1
                except Exception as e:
                    st.error(f"Failed to rename {files_data[i]['name']}: {e}")

            progress.progress(1.0, text="Done!")
            st.success(f"✅ {success_count} of {num_files} files renamed successfully!")
            st.session_state["rename_done"] = True
            st.session_state["output_dir"] = output_dir
            st.rerun()

    # After rename: show Open Folder button
    if st.session_state.get("rename_done"):
        final_dir = st.session_state.get("output_dir", output_dir)
        st.markdown("---")
        st.success(f"Files saved to: `{final_dir}`")
        if st.button("📂 Open Output Folder", type="primary", use_container_width=True):
            open_folder(final_dir)

        if st.button("🔄 Start Over", use_container_width=True):
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
