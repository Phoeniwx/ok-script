"""IPC client for communicating with ok-cli daemon."""

import json
from typing import Dict, Optional

from ok.cli.state import ConnectionManager


def ipc_call(cmd: str, params: Optional[Dict] = None, conn_id: Optional[str] = None) -> Dict:
    """Send command to daemon and return result."""
    import urllib.request

    daemon = ConnectionManager.get_daemon_info(conn_id)
    if daemon is None:
        cid = conn_id or ConnectionManager.load_index().get("latest")
        raise DaemonNotFoundError(
            f"No daemon found for connection '{cid}'. "
            f"Run 'ok-cli disconnect --cid {cid}' then 'ok-cli connect' to reconnect."
        )

    port = daemon["port"]
    url = f"http://127.0.0.1:{port}/command"
    req_body = json.dumps({"cmd": cmd, "params": params or {}}).encode("utf-8")

    try:
        resp = urllib.request.urlopen(url, data=req_body, timeout=30)
        result = json.loads(resp.read().decode("utf-8"))
        return result
    except urllib.error.URLError as e:
        cid = conn_id or ConnectionManager.load_index().get("latest")
        raise DaemonNotFoundError(
            f"Connection lost. "
            f"Run 'ok-cli disconnect --cid {cid}' then 'ok-cli connect' to reconnect."
        ) from e


def ipc_shutdown(conn_id: Optional[str] = None) -> bool:
    """Send shutdown command to daemon. Returns True if daemon was reachable."""
    import urllib.request

    daemon = ConnectionManager.get_daemon_info(conn_id)
    if daemon is None:
        return False

    port = daemon["port"]
    url = f"http://127.0.0.1:{port}/command"
    req_body = json.dumps({"cmd": "shutdown", "params": {}}).encode("utf-8")

    try:
        urllib.request.urlopen(url, data=req_body, timeout=5)
        return True
    except Exception:
        return False


class DaemonNotFoundError(Exception):
    pass
