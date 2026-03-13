"""Subprocess helpers — hide console windows on Windows."""

import subprocess
import sys


def _no_window_kwargs() -> dict:
    """Return kwargs to hide the console window on Windows."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}
