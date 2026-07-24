"""Run the legacy OpenPLC web UI on a configurable port.

OpenPLC_v3 hard-codes port 8080 in webserver.py.  This small launcher imports
the same Flask application and starts it on OPENPLC_WEB_PORT instead, without
modifying the third-party installation.
"""

import os
import sys
from pathlib import Path


def main() -> None:
    if os.name == "nt":
        username = os.environ.get("USERNAME", "")
        webserver_dir = Path(f"C:/msys64/home/{username}/OpenPLC_v3/webserver")
    else:
        webserver_dir = Path.home() / "OpenPLC_v3" / "webserver"
    if not (webserver_dir / "webserver.py").is_file():
        raise SystemExit(f"OpenPLC webserver not found: {webserver_dir}")

    os.chdir(webserver_dir)
    sys.path.insert(0, str(webserver_dir))

    import webserver  # pylint: disable=import-outside-toplevel

    port = int(os.environ.get("OPENPLC_WEB_PORT", "8080"))
    webserver.app.run(debug=False, host="0.0.0.0", threaded=True, port=port)


if __name__ == "__main__":
    main()
