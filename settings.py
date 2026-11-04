"""Server-only configuration: process env > Streamlit Secrets > local .env."""
import os
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent


def setting(name, default=""):
    if name in os.environ:
        return os.environ[name]
    try:
        import streamlit as st
        if name in st.secrets:
            return str(st.secrets[name])
    except (FileNotFoundError, RuntimeError):
        pass
    value = dotenv_values(ROOT / ".env").get(name)
    return str(value) if value is not None else default


def cloud_runtime():
    # Additional guard when the host supplies this marker. Deployment still explicitly sets STORAGE_BACKEND.
    return os.getenv("STREAMLIT_SHARING_MODE") is not None
