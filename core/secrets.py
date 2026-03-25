from __future__ import annotations

import os


def get_secret(key: str) -> str | None:
    """Get secret from Streamlit Cloud secrets first, then fall back to env vars."""
    try:
        import streamlit as st
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.getenv(key)
