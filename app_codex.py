"""PLC-Assist Codex edition entrypoint.

Run with:
    streamlit run app_codex.py --server.port 8502
"""

import os
import runpy
from pathlib import Path


os.environ["PLC_ASSIST_PROVIDER"] = "codex"
runpy.run_path(str(Path(__file__).with_name("app.py")), run_name="__main__")
