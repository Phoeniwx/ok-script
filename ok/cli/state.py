"""Persistent connection state for ok-cli."""

import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional


class ConnectionManager:
    """Manages ok-cli connection metadata under ~/.ok-cli."""

    BASE_DIR = Path.home() / ".ok-cli"
    INDEX_NAME = "connections.json"

    @classmethod
    def ensure_dir(cls):
        cls.BASE_DIR.mkdir(exist_ok=True)

    @classmethod
    def get_index_path(cls) -> Path:
        return cls.BASE_DIR / cls.INDEX_NAME

    @classmethod
    def load_index(cls) -> dict:
        path = cls.get_index_path()
        if not path.exists():
            return {"latest": None, "connections": {}}

        try:
            index = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"latest": None, "connections": {}}

        if not isinstance(index, dict):
            return {"latest": None, "connections": {}}
        index.setdefault("latest", None)
        index.setdefault("connections", {})
        return index

    @classmethod
    def save_index(cls, index: dict):
        cls.ensure_dir()
        path = cls.get_index_path()
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, path)

    @classmethod
    def create_connection(cls, mode: str, target: dict, config: dict) -> str:
        conn_id = uuid.uuid4().hex[:8]
        index = cls.load_index()
        index["connections"][conn_id] = {
            "mode": mode,
            "target": target,
            "config": config,
            "created": datetime.now().isoformat(),
        }
        index["latest"] = conn_id
        cls.save_index(index)
        return conn_id

    @classmethod
    def get_connection_info(cls, conn_id: Optional[str] = None) -> Optional[dict]:
        index = cls.load_index()
        if conn_id is None:
            conn_id = index.get("latest")
        if conn_id:
            return index.get("connections", {}).get(conn_id)
        return None

    @classmethod
    def get_daemon_info(cls, conn_id: Optional[str] = None) -> Optional[Dict]:
        info = cls.get_connection_info(conn_id)
        if not info:
            return None
        daemon = info.get("daemon")
        return daemon if isinstance(daemon, dict) else None

    @classmethod
    def update_daemon_info(cls, conn_id: str, pid: int, port: int):
        index = cls.load_index()
        if conn_id not in index.get("connections", {}):
            return
        index["connections"][conn_id]["daemon"] = {
            "pid": pid,
            "port": port,
            "started": datetime.now().isoformat(),
        }
        cls.save_index(index)

    @classmethod
    def delete_connection(cls, conn_id: str):
        index = cls.load_index()
        connections = index.get("connections", {})
        if conn_id in connections:
            del connections[conn_id]
            if index.get("latest") == conn_id:
                keys = list(connections.keys())
                index["latest"] = keys[-1] if keys else None
            cls.save_index(index)

    @classmethod
    def list_connections(cls) -> dict:
        return cls.load_index()

    @classmethod
    def wait_for_daemon_port(cls, conn_id: str, timeout: float = 30.0) -> Optional[int]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            daemon = cls.get_daemon_info(conn_id)
            port = daemon.get("port") if daemon else None
            if port:
                return port
            time.sleep(0.2)
        return None
