"""PLC-Assist llama.cpp MTP edition entrypoint.

Run with:
    streamlit run app_llamacpp.py --server.port 8503
"""

import os
import runpy
from pathlib import Path


os.environ["PLC_ASSIST_PROVIDER"] = "llamacpp"
runpy.run_path(str(Path(__file__).with_name("app.py")), run_name="__main__")
