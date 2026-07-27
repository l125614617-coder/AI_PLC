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
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


def _config_file() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "service-manager-config.json"
    return Path(__file__).resolve().parent / ".runlogs" / "service-manager-config.json"


CONFIG_FILE = _config_file()


def _valid_project_root(path: Path) -> bool:
    return (
        (path / "app.py").is_file()
        and (path / "venv" / "Scripts" / "python.exe").is_file()
        and (path / "setup" / "start_llamacpp.ps1").is_file()
    )


def _parents(path: Path):
    yield path
    yield from path.parents


def _saved_project_root() -> Path | None:
    try:
        value = json.loads(CONFIG_FILE.read_text(encoding="utf-8")).get("project_root")
        return Path(value).resolve() if value else None
    except (OSError, ValueError, AttributeError):
        return None


def _project_root() -> Path:
    configured = os.environ.get("PLC_ASSIST_ROOT")
    candidates = []
    if configured:
        candidates.append(Path(configured))
    saved = _saved_project_root()
    if saved:
        candidates.append(saved)
    for anchor in (
        Path(__file__).resolve().parent,
        Path(sys.executable).resolve().parent,
        Path.cwd().resolve(),
    ):
        candidates.extend(_parents(anchor))
    seen = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if _valid_project_root(resolved):
            return resolved
    return Path(configured).resolve() if configured else Path.cwd().resolve()


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
    ready_timeout: float = 20.0


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
        120.0,
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


class ServiceStartError(RuntimeError):
    pass


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
        if os.name == "nt":
            return bool(ServiceManager._pid_command(pid))
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ValueError):
            return False

    @staticmethod
    def _pid_command(pid: int) -> str:
        if os.name != "nt":
            return ""
        script = (
            f"$p=Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\" "
            "-ErrorAction SilentlyContinue; if($p){$p.CommandLine}"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return result.stdout.strip()

    def _owned_process_matches(self, pid: int, entry: dict) -> bool:
        if not self._pid_alive(pid):
            return False
        fingerprint = str(entry.get("fingerprint") or "")
        if not fingerprint:
            return False
        command_line = self._pid_command(pid)
        return fingerprint.lower() in command_line.lower()

    @staticmethod
    def _listener_pid(service: Service) -> int | None:
        if os.name != "nt":
            return None
        parsed = urlparse(service.health_url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        script = (
            f"$c=Get-NetTCPConnection -LocalPort {port} -State Listen "
            "-ErrorAction SilentlyContinue | Select-Object -First 1; "
            "if($c){$c.OwningProcess}"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            return int(result.stdout.strip())
        except ValueError:
            return None

    @staticmethod
    def _fingerprint(key: str, command: list[str]) -> str:
        if key.startswith("ui_"):
            return next((arg for arg in command if arg.lower().endswith(".py")), command[0])
        if key == "llamacpp":
            return "start_llamacpp.ps1"
        if key == "openplc":
            return "run_openplc.py"
        return "ollama"

    @staticmethod
    def _tail(path: Path, max_chars: int = 3000) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace")[-max_chars:].strip()
        except OSError:
            return ""

    def preflight(self, key: str) -> list[str]:
        missing = []
        if key == "ollama" and not shutil.which("ollama"):
            missing.append("Ollama executable was not found in PATH")
        if key.startswith("ui_"):
            if not PYTHON.is_file():
                missing.append(f"Python environment not found: {PYTHON}")
            entrypoint = {
                "ui_ollama": "app.py",
                "ui_codex": "app_codex.py",
                "ui_llamacpp": "app_llamacpp.py",
            }[key]
            if not (ROOT / entrypoint).is_file():
                missing.append(f"UI entrypoint not found: {ROOT / entrypoint}")
        if key == "ui_codex":
            codex = shutil.which("codex")
            if not codex:
                missing.append("Codex CLI was not found in PATH")
            else:
                login = subprocess.run(
                    [codex, "login", "status"],
                    capture_output=True,
                    text=True,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if login.returncode != 0:
                    missing.append("Codex CLI is not logged in; run `codex login`")
        if key == "llamacpp":
            for path, label in (
                (ROOT / "setup" / "start_llamacpp.ps1", "llama.cpp launcher"),
                (ROOT / "tools" / "llama.cpp" / "llama-server.exe", "llama-server"),
                (ROOT / "models" / "Qwen3.6-27B-Q3_K_M.gguf", "27B model"),
            ):
                if not path.is_file():
                    missing.append(f"{label} not found: {path}")
        if key == "openplc":
            if not BASH.is_file():
                missing.append(f"MSYS2 bash not found: {BASH}")
            if not (ROOT / "setup" / "start_openplc.sh").is_file():
                missing.append(f"OpenPLC launcher not found: {ROOT / 'setup' / 'start_openplc.sh'}")
            openplc_python = (
                Path("C:/msys64/home")
                / os.environ.get("USERNAME", "")
                / "OpenPLC_v3"
                / ".venv"
                / "bin"
                / "python3"
            )
            if not openplc_python.is_file():
                missing.append(f"OpenPLC Python not found: {openplc_python}")
        return missing

    def status(self, key: str) -> dict:
        service = SERVICES[key]
        entry = self.state.get(key) or {}
        pid = int(entry.get("pid") or 0)
        owned = bool(pid and self._owned_process_matches(pid, entry))
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
            "state": "ready" if online else ("starting" if owned else "stopped"),
            "url": service.page_url,
            "project_root": str(ROOT),
        }

    def start(self, key: str) -> dict:
        service = SERVICES[key]
        current = self.status(key)
        if current["online"]:
            return current
        problems = self.preflight(key)
        if problems:
            raise ServiceStartError("\n".join(problems))

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
            "fingerprint": self._fingerprint(key, command),
            "started_at": time.time(),
        }
        self._save_state()
        deadline = time.monotonic() + service.ready_timeout
        while time.monotonic() < deadline:
            if healthy(service):
                listener_pid = self._listener_pid(service)
                if listener_pid:
                    fingerprint = self.state[key]["fingerprint"]
                    listener_command = self._pid_command(listener_pid)
                    if fingerprint.lower() in listener_command.lower():
                        self.state[key]["pid"] = listener_pid
                        self._save_state()
                return self.status(key)
            if process.poll() is not None:
                break
            time.sleep(0.5)

        self.state.pop(key, None)
        self._save_state()
        if process.poll() is None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            else:
                process.terminate()
        detail = self._tail(stderr_path) or self._tail(stdout_path)
        reason = (
            f"{service.label} exited before becoming ready"
            if process.poll() is not None
            else f"{service.label} did not become ready within {service.ready_timeout:.0f}s"
        )
        raise ServiceStartError(f"{reason}.\n{detail}".strip())

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
        results = []
        newly_started = []
        try:
            for key in keys:
                was_online = self.status(key)["online"]
                results.append(self.start(key))
                if not was_online:
                    newly_started.append(key)
            return results
        except Exception:
            for key in reversed(newly_started):
                self.stop(key)
            raise

    def stop_all_managed(self) -> list[dict]:
        return [self.stop(key) for key in reversed(tuple(SERVICES))]


def run_gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("PLC-Assist Service Manager")
    root.geometry("850x520")
    manager = ServiceManager()
    status_vars = {key: tk.StringVar(value="檢查中") for key in SERVICES}
    mtp_var = tk.IntVar(value=2)
    openplc_var = tk.BooleanVar(value=False)
    project_var = tk.StringVar(value=str(ROOT))

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

    def run_start(action) -> None:
        manager.mtp_tokens = mtp_var.get()

        def worker():
            try:
                action()
            except (OSError, ServiceStartError) as exc:
                root.after(0, lambda: messagebox.showerror("啟動失敗", str(exc)))
            finally:
                root.after(0, refresh)

        threading.Thread(target=worker, daemon=True).start()

    def start_mode(mode: str) -> None:
        run_start(
            lambda: manager.start_mode(
                mode,
                include_openplc=openplc_var.get(),
            )
        )

    def start_service(key: str) -> None:
        status_vars[key].set("◌ 啟動中")
        run_start(lambda: manager.start(key))

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

    def choose_project() -> None:
        selected = filedialog.askdirectory(
            title="選擇 PLC-Assist 專案資料夾",
            initialdir=str(ROOT),
        )
        if not selected:
            return
        selected_path = Path(selected).resolve()
        if not _valid_project_root(selected_path):
            messagebox.showerror(
                "資料夾不完整",
                "必須包含 app.py、venv\\Scripts\\python.exe 與 "
                "setup\\start_llamacpp.ps1。",
            )
            return
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(
            json.dumps({"project_root": str(selected_path)}, indent=2),
            encoding="utf-8",
        )
        project_var.set(str(selected_path))
        messagebox.showinfo("設定已儲存", "請重新啟動 Service Manager 套用新路徑。")

    project = ttk.Frame(root, padding=(12, 10, 12, 0))
    project.pack(fill="x")
    ttk.Label(project, text="專案：").pack(side="left")
    ttk.Label(project, textvariable=project_var).pack(side="left", fill="x", expand=True)
    ttk.Button(project, text="選擇資料夾", command=choose_project).pack(side="right")

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
    parser.add_argument(
        "action",
        nargs="?",
        choices=("gui", "status", "preflight", "start", "stop"),
        default="gui",
    )
    parser.add_argument("target", nargs="?", choices=tuple(SERVICES) + tuple(MODES))
    parser.add_argument("--mtp-tokens", type=int, choices=range(0, 9), default=2)
    parser.add_argument("--openplc", action="store_true")
    args = parser.parse_args()
    if args.action == "gui":
        run_gui()
        return 0

    manager = ServiceManager(mtp_tokens=args.mtp_tokens)
    try:
        if args.action == "status":
            result = [manager.status(key) for key in SERVICES]
        elif not args.target:
            parser.error("preflight/start/stop requires a service or mode target")
        elif args.action == "preflight":
            keys = MODES.get(args.target, (args.target,))
            result = []
            for key in keys:
                issues = manager.preflight(key)
                result.append({"key": key, "ok": not issues, "issues": issues})
        elif args.action == "start" and args.target in MODES:
            result = manager.start_mode(args.target, include_openplc=args.openplc)
        elif args.action == "start":
            result = [manager.start(args.target)]
        elif args.target in MODES:
            keys = MODES[args.target]
            result = [manager.stop(key) for key in reversed(keys)]
        else:
            result = [manager.stop(args.target)]
    except ServiceStartError as exc:
        print(json.dumps({
            "status": "failed",
            "project_root": str(ROOT),
            "error": str(exc),
        }, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
