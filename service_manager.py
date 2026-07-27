"""PLC-Assist local service manager.

Provides both a small Tkinter GUI and a CLI suitable for smoke tests:

    python service_manager.py
    python service_manager.py status
    python service_manager.py start ollama
    python service_manager.py stop llamacpp
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import time
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path


def _project_root() -> Path:
    configured = os.environ.get("PLC_ASSIST_ROOT")
    if configured:
        return Path(configured).resolve()
    source_root = Path(__file__).resolve().parent
    if (source_root / "app.py").is_file():
        return source_root
    executable_root = Path(sys.executable).resolve().parent
    if (executable_root / "app.py").is_file():
        return executable_root
    return source_root


ROOT = _project_root()
RUN_DIR = ROOT / ".runlogs"
STATE_FILE = RUN_DIR / "service-manager-state.json"
PYTHON = ROOT / "venv" / "Scripts" / "python.exe"
BASH = Path("C:/msys64/usr/bin/bash.exe")


def _msys_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    suffix = resolved.as_posix().split(":", 1)[-1]
    return f"/{drive}{suffix}" if drive else resolved.as_posix()


@dataclass(frozen=True)
class Service:
    key: str
    label: str
    health_url: str
    page_url: str
    command: tuple[str, ...]


def _streamlit(entrypoint: str, port: int) -> tuple[str, ...]:
    return (
        str(PYTHON),
        "-m",
        "streamlit",
        "run",
        str(ROOT / entrypoint),
        "--server.port",
        str(port),
        "--server.headless",
        "true",
    )


SERVICES = {
    "ollama": Service(
        "ollama",
        "Ollama API",
        "http://127.0.0.1:11434/api/tags",
        "http://127.0.0.1:11434",
        ("ollama", "serve"),
    ),
    "ui_ollama": Service(
        "ui_ollama",
        "Ollama UI",
        "http://127.0.0.1:8501/_stcore/health",
        "http://127.0.0.1:8501",
        _streamlit("app.py", 8501),
    ),
    "ui_codex": Service(
        "ui_codex",
        "Codex UI",
        "http://127.0.0.1:8502/_stcore/health",
        "http://127.0.0.1:8502",
        _streamlit("app_codex.py", 8502),
    ),
    "llamacpp": Service(
        "llamacpp",
        "llama.cpp API",
        "http://127.0.0.1:8082/health",
        "http://127.0.0.1:8082",
        (
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "setup" / "start_llamacpp.ps1"),
        ),
    ),
    "ui_llamacpp": Service(
        "ui_llamacpp",
        "llama.cpp UI",
        "http://127.0.0.1:8503/_stcore/health",
        "http://127.0.0.1:8503",
        _streamlit("app_llamacpp.py", 8503),
    ),
    "openplc": Service(
        "openplc",
        "OpenPLC",
        "http://127.0.0.1:8081/login",
        "http://127.0.0.1:8081/login",
        (
            str(BASH),
            "-lc",
            "OPENPLC_WEB_PORT=8081 "
            + shlex.quote(f"{_msys_path(ROOT)}/setup/start_openplc.sh"),
        ),
    ),
}

MODES = {
    "ollama": ("ollama", "ui_ollama"),
    "codex": ("ui_codex",),
    "llamacpp": ("llamacpp", "ui_llamacpp"),
    "simulation": ("openplc",),
    "all": tuple(SERVICES),
}


def healthy(service: Service, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(service.health_url, timeout=timeout) as response:
            return 200 <= response.status < 500
    except (OSError, ValueError):
        return False


class ServiceManager:
    def __init__(self, mtp_tokens: int = 2):
        self.mtp_tokens = mtp_tokens
        RUN_DIR.mkdir(exist_ok=True)
        self.state = self._load_state()

    @staticmethod
    def _load_state() -> dict:
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_state(self) -> None:
        STATE_FILE.write_text(
            json.dumps(self.state, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ValueError):
            return False

    def status(self, key: str) -> dict:
        service = SERVICES[key]
        entry = self.state.get(key) or {}
        pid = int(entry.get("pid") or 0)
        owned = bool(pid and self._pid_alive(pid))
        online = healthy(service)
        if pid and not owned:
            self.state.pop(key, None)
            self._save_state()
        return {
            "key": key,
            "label": service.label,
            "online": online,
            "owned": owned,
            "pid": pid if owned else None,
            "source": "managed" if owned else ("external" if online else "stopped"),
            "url": service.page_url,
        }

    def start(self, key: str) -> dict:
        service = SERVICES[key]
        current = self.status(key)
        if current["online"]:
            return current

        command = list(service.command)
        if key == "llamacpp":
            command.extend(["-MtpTokens", str(self.mtp_tokens)])

        stdout_path = RUN_DIR / f"manager-{key}.out.log"
        stderr_path = RUN_DIR / f"manager-{key}.err.log"
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with stdout_path.open("ab") as stdout, stderr_path.open("ab") as stderr:
            child_env = os.environ.copy()
            child_env.setdefault("OPENPLC_WEB_BASE", "http://127.0.0.1:8081")
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdout=stdout,
                stderr=stderr,
                env=child_env,
                creationflags=creationflags,
            )
        self.state[key] = {
            "pid": process.pid,
            "command": command,
            "started_at": time.time(),
        }
        self._save_state()
        return self.status(key)

    def stop(self, key: str) -> dict:
        current = self.status(key)
        if current["owned"] and current["pid"]:
            pid = int(current["pid"])
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            else:
                os.kill(pid, signal.SIGTERM)
            self.state.pop(key, None)
            self._save_state()
        return self.status(key)

    def start_mode(self, mode: str, include_openplc: bool = False) -> list[dict]:
        keys = list(MODES[mode])
        if include_openplc and "openplc" not in keys:
            keys.append("openplc")
        return [self.start(key) for key in keys]

    def stop_all_managed(self) -> list[dict]:
        return [self.stop(key) for key in reversed(tuple(SERVICES))]


def run_gui() -> None:
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title("PLC-Assist Service Manager")
    root.geometry("780x470")
    manager = ServiceManager()
    status_vars = {key: tk.StringVar(value="檢查中") for key in SERVICES}
    mtp_var = tk.IntVar(value=2)
    openplc_var = tk.BooleanVar(value=False)

    def refresh() -> None:
        for key in SERVICES:
            info = manager.status(key)
            text = "● 線上"
            if info["source"] == "managed":
                text += f"（PID {info['pid']}）"
            elif info["source"] == "external":
                text += "（外部程序）"
            else:
                text = "○ 已停止"
            status_vars[key].set(text)

    def start_mode(mode: str) -> None:
        manager.mtp_tokens = mtp_var.get()
        try:
            manager.start_mode(mode, include_openplc=openplc_var.get())
            root.after(800, refresh)
        except OSError as exc:
            messagebox.showerror("啟動失敗", str(exc))

    def start_service(key: str) -> None:
        manager.mtp_tokens = mtp_var.get()
        try:
            manager.start(key)
            root.after(800, refresh)
        except OSError as exc:
            messagebox.showerror("啟動失敗", str(exc))

    def stop_service(key: str) -> None:
        info = manager.status(key)
        if info["source"] == "external":
            messagebox.showinfo("外部程序", "此服務不是由管理器啟動，因此不會強制停止。")
            return
        manager.stop(key)
        root.after(300, refresh)

    def open_log(key: str) -> None:
        log_path = RUN_DIR / f"manager-{key}.err.log"
        log_path.touch(exist_ok=True)
        os.startfile(log_path)

    top = ttk.Frame(root, padding=12)
    top.pack(fill="x")
    ttk.Label(top, text="啟動模式：").pack(side="left")
    for mode, label in (
        ("ollama", "快速本機"),
        ("codex", "Codex"),
        ("llamacpp", "27B 高品質"),
        ("all", "全部測試"),
    ):
        ttk.Button(top, text=label, command=lambda m=mode: start_mode(m)).pack(
            side="left", padx=4
        )
    ttk.Checkbutton(top, text="同時啟動 OpenPLC", variable=openplc_var).pack(
        side="left", padx=12
    )

    options = ttk.Frame(root, padding=(12, 0))
    options.pack(fill="x")
    ttk.Label(options, text="llama.cpp MTP tokens：").pack(side="left")
    ttk.Spinbox(options, from_=0, to=8, width=4, textvariable=mtp_var).pack(
        side="left"
    )
    ttk.Button(options, text="重新整理", command=refresh).pack(side="right")

    table = ttk.Frame(root, padding=12)
    table.pack(fill="both", expand=True)
    for row, (key, service) in enumerate(SERVICES.items()):
        ttk.Label(table, text=service.label, width=20).grid(
            row=row, column=0, sticky="w", pady=5
        )
        ttk.Label(table, textvariable=status_vars[key], width=25).grid(
            row=row, column=1, sticky="w"
        )
        ttk.Button(table, text="啟動", command=lambda k=key: start_service(k)).grid(
            row=row, column=2, padx=3
        )
        ttk.Button(table, text="停止", command=lambda k=key: stop_service(k)).grid(
            row=row, column=3, padx=3
        )
        ttk.Button(
            table,
            text="開啟",
            command=lambda url=service.page_url: webbrowser.open(url),
        ).grid(row=row, column=4, padx=3)
        ttk.Button(
            table,
            text="日誌",
            command=lambda k=key: open_log(k),
        ).grid(row=row, column=5, padx=3)

    bottom = ttk.Frame(root, padding=12)
    bottom.pack(fill="x")
    ttk.Button(
        bottom,
        text="停止管理器啟動的全部服務",
        command=lambda: (manager.stop_all_managed(), refresh()),
    ).pack(side="right")
    ttk.Label(
        bottom,
        text="外部程序只顯示狀態，不會被管理器停止。",
    ).pack(side="left")
    refresh()
    root.mainloop()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", nargs="?", choices=("gui", "status", "start", "stop"), default="gui")
    parser.add_argument("target", nargs="?", choices=tuple(SERVICES) + tuple(MODES))
    parser.add_argument("--mtp-tokens", type=int, choices=range(0, 9), default=2)
    parser.add_argument("--openplc", action="store_true")
    args = parser.parse_args()
    if args.action == "gui":
        run_gui()
        return 0

    manager = ServiceManager(mtp_tokens=args.mtp_tokens)
    if args.action == "status":
        result = [manager.status(key) for key in SERVICES]
    elif not args.target:
        parser.error("start/stop requires a service or mode target")
    elif args.action == "start" and args.target in MODES:
        result = manager.start_mode(args.target, include_openplc=args.openplc)
    elif args.action == "start":
        result = [manager.start(args.target)]
    elif args.target in MODES:
        keys = MODES[args.target]
        result = [manager.stop(key) for key in reversed(keys)]
    else:
        result = [manager.stop(args.target)]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
