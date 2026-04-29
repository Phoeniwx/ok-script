"""Context for ok-cli connection management."""

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Optional

from ok.cli.state import ConnectionManager


class Context:
    """Connection management utilities (daemon launching, polling)."""

    _current_conn_id: Optional[str] = None

    @classmethod
    def _ipc_request(cls, port: int, cmd: str, params: Optional[dict] = None, timeout: float = 2.0) -> dict:
        import urllib.request

        req = json.dumps({"cmd": cmd, "params": params or {}}).encode("utf-8")
        resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/command", data=req, timeout=timeout)
        return json.loads(resp.read().decode("utf-8"))

    @classmethod
    def _cleanup_stale_connections(cls):
        """Remove saved connections whose daemon port no longer responds."""
        index = ConnectionManager.load_index()
        for cid, info in index.get("connections", {}).items():
            daemon = info.get("daemon", {})
            port = daemon.get("port")
            if not port:
                continue
            try:
                cls._ipc_request(port, "ping", timeout=1.5)
            except Exception:
                ConnectionManager.delete_connection(cid)

    @staticmethod
    def _normalize_exe(value) -> set[str]:
        if not value:
            return set()
        values = value if isinstance(value, (list, tuple, set)) else [value]
        return {Path(str(item)).name.lower() for item in values if item}

    @classmethod
    def _connection_is_alive(cls, cid: str) -> bool:
        daemon = ConnectionManager.get_daemon_info(cid)
        port = daemon.get("port") if daemon else None
        if not port:
            return False
        try:
            result = cls._ipc_request(port, "ping", timeout=1.5)
            return bool(result.get("success"))
        except Exception:
            ConnectionManager.delete_connection(cid)
            return False

    @classmethod
    def _find_existing_connection(cls, mode: str, target: dict) -> Optional[str]:
        index = ConnectionManager.load_index()
        for cid, info in index.get("connections", {}).items():
            if info.get("mode") != mode:
                continue
            if mode == "desktop":
                target_match = True
            else:
                saved_target = info.get("target", {})
                title = target.get("title")
                exe_names = cls._normalize_exe(target.get("exe"))
                saved_exe_names = cls._normalize_exe(saved_target.get("exe"))
                target_match = bool(
                    (title and title == saved_target.get("title"))
                    or (exe_names and saved_exe_names and exe_names == saved_exe_names)
                )
            if target_match and cls._connection_is_alive(cid):
                return cid
        return None

    @staticmethod
    def _base_windows_config() -> dict:
        return {
            "use_gui": False,
            "windows": {
                "capture_method": ["WGC", "BitBlt_RenderFull", "BitBlt", "DXGI"],
                "interaction": "PyDirect",
            },
        }

    @classmethod
    def _wait_until_ready(cls, conn_id: str, timeout: float = 30.0) -> dict:
        port = ConnectionManager.wait_for_daemon_port(conn_id, timeout=timeout)
        if not port:
            raise RuntimeError("Daemon did not publish an IPC port within timeout")

        deadline = time.time() + timeout
        last_error = "Daemon not ready"
        while time.time() < deadline:
            try:
                result = cls._ipc_request(port, "screen_info", timeout=5)
                if result.get("success"):
                    return result.get("data", {})
                last_error = result.get("error", last_error)
            except Exception as exc:
                last_error = str(exc)
            time.sleep(0.5)
        raise RuntimeError(f"Daemon not ready within timeout: {last_error}")

    @classmethod
    def init_window(cls, exe: Optional[str] = None, title: Optional[str] = None) -> Dict:
        """Create a window connection and start daemon."""
        cls._cleanup_stale_connections()

        target = {"exe": exe, "title": title}
        if existing := cls._find_existing_connection("window", target):
            return {
                "success": False,
                "error": f"Window already connected. Run 'ok-cli disconnect --cid {existing}' first, or use 'ok-cli screen-info --cid {existing}'.",
                "connection_id": existing,
            }

        config = cls._base_windows_config()
        if exe:
            config["windows"]["exe"] = [exe] if isinstance(exe, str) else exe
        if title:
            config["windows"]["title"] = title

        conn_id = ConnectionManager.create_connection(mode="window", target=target, config=config)
        cls._start_daemon(conn_id)
        try:
            screen_info = cls._wait_until_ready(conn_id)
        except Exception:
            ConnectionManager.delete_connection(conn_id)
            raise
        cls._current_conn_id = conn_id
        return {
            "success": True,
            "mode": "window",
            "target": target,
            "connection_id": conn_id,
            "screen_info": screen_info,
        }

    @classmethod
    def init_desktop(cls) -> Dict:
        """Create a desktop connection and start daemon."""
        cls._cleanup_stale_connections()

        target = {"type": "desktop"}
        if existing := cls._find_existing_connection("desktop", target):
            return {
                "success": False,
                "error": f"Desktop already connected. Run 'ok-cli disconnect --cid {existing}' first, or use 'ok-cli screen-info --cid {existing}'.",
                "connection_id": existing,
            }

        config = cls._base_windows_config()
        conn_id = ConnectionManager.create_connection(mode="desktop", target=target, config=config)

        cls._start_daemon(conn_id)
        try:
            screen_info = cls._wait_until_ready(conn_id)
        except Exception:
            ConnectionManager.delete_connection(conn_id)
            raise
        cls._current_conn_id = conn_id
        return {
            "success": True,
            "mode": "desktop",
            "target": target,
            "connection_id": conn_id,
            "screen_info": screen_info,
        }

    @classmethod
    def _start_daemon(cls, conn_id: str):
        pythonw = sys.executable.replace("python.exe", "pythonw.exe")
        ConnectionManager.ensure_dir()
        stderr_path = ConnectionManager.BASE_DIR / f"daemon-{conn_id}.stderr"
        executable = pythonw if Path(pythonw).exists() else sys.executable
        with open(stderr_path, "w", encoding="utf-8") as stderr_file:
            subprocess.Popen(
                [executable, "-m", "ok.cli.daemon", conn_id],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=stderr_file,
            )

    @classmethod
    def disconnect(cls, conn_id: str = None) -> str:
        if conn_id is None:
            conn_id = cls._current_conn_id
        if conn_id is None:
            conn_id = ConnectionManager.load_index().get("latest")

        if conn_id:
            from ok.cli.ipc_client import ipc_shutdown

            ipc_shutdown(conn_id)
            ConnectionManager.delete_connection(conn_id)

        cls._current_conn_id = None
        return conn_id
