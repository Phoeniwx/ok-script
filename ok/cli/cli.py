"""Main CLI module for ok-cli."""

import json
import os
import sys
from typing import Optional

# Disable QFluentWidgets tip message
os.environ["DISABLE_QFluentWidgets_TIPS"] = "1"

import click

from ok.cli.bootstrap import prepare_cli_environment
from ok.cli.context import Context
from ok.cli.ipc_client import DaemonNotFoundError, ipc_call
from ok.cli.state import ConnectionManager

prepare_cli_environment()


def _success(data: dict) -> str:
    return json.dumps({"success": True, "data": data}, ensure_ascii=False)


def _error(message: str) -> str:
    return json.dumps({"success": False, "error": message}, ensure_ascii=False)


def _resolve_conn_id(cid: Optional[str]) -> str:
    """Resolve connection ID: explicit or latest."""
    if cid:
        return cid
    latest = ConnectionManager.load_index().get("latest")
    if not latest:
        raise DaemonNotFoundError(
            "No active connection. Run 'ok-cli connect --desktop' or "
            "'ok-cli connect --exe <name>' to create one."
        )
    return latest


def _dispatch(cmd: str, params: Optional[dict] = None, cid: Optional[str] = None):
    """Send command to daemon and print result."""
    try:
        resolved_cid = _resolve_conn_id(cid)
        result = ipc_call(cmd, params, resolved_cid)
        if result.get("success"):
            print(_success(result.get("data", {})))
        else:
            print(_error(result.get("error", "Unknown error")))
        sys.exit(0 if result.get("success") else 1)
    except DaemonNotFoundError as e:
        print(_error(str(e)))
        sys.exit(1)


@click.group()
def cli():
    """ok-cli - CLI wrapper for ok-script screen automation."""
    pass


@cli.command()
@click.option("--desktop", is_flag=True, help="Connect to desktop mode")
@click.option("--exe", type=str, help="Connect to window by exe name")
@click.option("--title", type=str, help="Connect to window by title")
def connect(desktop: bool, exe: Optional[str], title: Optional[str]):
    """Connect to desktop or window."""
    try:
        if desktop:
            result = Context.init_desktop()
        elif exe or title:
            result = Context.init_window(exe=exe, title=title)
        else:
            print(_error("Either --desktop or --exe/--title must be provided"))
            sys.exit(1)
        if not result.get("success"):
            print(_error(result.get("error", "Connection failed")))
            sys.exit(1)
        print(_success(result))
    except Exception as e:
        print(_error(str(e)))
        sys.exit(1)


@cli.command()
@click.option("--cid", "--connection-id", help="Connection ID to disconnect (default: latest)")
def disconnect(cid: Optional[str]):
    """Disconnect a connection."""
    try:
        resolved_cid = _resolve_conn_id(cid) if cid else None
        conn_id = Context.disconnect(resolved_cid)
        print(_success({"status": "disconnected", "connection_id": conn_id}))
    except DaemonNotFoundError as e:
        print(_error(str(e)))
        sys.exit(1)
    except Exception as e:
        print(_error(str(e)))
        sys.exit(1)


@cli.command(name="list-connections")
def list_connections():
    """List all saved connections."""
    try:
        result = ConnectionManager.list_connections()
        print(_success(result))
    except Exception as e:
        print(_error(str(e)))
        sys.exit(1)


@cli.command()
@click.option("--cid", "--connection-id", help="Connection ID to use (default: latest)")
def screen_info(cid: Optional[str]):
    """Get screen/window resolution."""
    _dispatch("screen_info", {}, cid)


@cli.command()
@click.option("--output", "-o", type=str, required=True, help="Output PNG file path")
@click.option("--cid", "--connection-id", help="Connection ID to use (default: latest)")
def screenshot(output: str, cid: Optional[str]):
    """Take screenshot."""
    _dispatch("screenshot", {"output": output}, cid)


@cli.command(name="crop")
@click.option("--x", "-x", type=int, required=True, help="Center X coordinate in screenshot space")
@click.option("--y", "-y", type=int, required=True, help="Center Y coordinate in screenshot space")
@click.option("--size", "-s", type=int, default=80, show_default=True, help="Square side length in pixels")
@click.option("--output", "-o", type=str, required=True, help="Output PNG file path")
@click.option("--cid", "--connection-id", help="Connection ID to use (default: latest)")
def crop(x: int, y: int, size: int, output: str, cid: Optional[str]):
    """Crop a square image centered at screenshot coordinates."""
    if size <= 0:
        print(_error("size must be greater than 0"))
        sys.exit(1)
    _dispatch("crop", {"x": x, "y": y, "size": size, "output": output}, cid)


@cli.command(name="crop-rel")
@click.option("--x", "-x", type=float, required=True, help="Relative center X (0-1)")
@click.option("--y", "-y", type=float, required=True, help="Relative center Y (0-1)")
@click.option("--size", "-s", type=int, default=80, show_default=True, help="Square side length in screenshot pixels")
@click.option("--output", "-o", type=str, required=True, help="Output PNG file path")
@click.option("--cid", "--connection-id", help="Connection ID to use (default: latest)")
def crop_rel(x: float, y: float, size: int, output: str, cid: Optional[str]):
    """Crop a square image centered at relative coordinates."""
    if not 0 <= x <= 1 or not 0 <= y <= 1:
        print(_error("relative coordinates must be between 0 and 1"))
        sys.exit(1)
    if size <= 0:
        print(_error("size must be greater than 0"))
        sys.exit(1)
    _dispatch("crop_rel", {"x": x, "y": y, "size": size, "output": output}, cid)


@cli.command(name="click")
@click.option("--x", "-x", type=int, required=True, help="X coordinate")
@click.option("--y", "-y", type=int, required=True, help="Y coordinate")
@click.option("--button", "-b", type=str, default="left", help="Mouse button (left/right/middle)")
@click.option("--after-sleep", type=float, default=0, help="Sleep time after click (seconds)")
@click.option("--cid", "--connection-id", help="Connection ID to use (default: latest)")
def do_click(x: int, y: int, button: str, after_sleep: float, cid: Optional[str]):
    """Click at absolute coordinates."""
    if button not in {"left", "right", "middle"}:
        print(_error("button must be one of: left, right, middle"))
        sys.exit(1)
    _dispatch("click", {"x": x, "y": y, "button": button, "after_sleep": after_sleep}, cid)


@cli.command()
@click.option("--x", "-x", type=float, required=True, help="Relative X (0-1)")
@click.option("--y", "-y", type=float, required=True, help="Relative Y (0-1)")
@click.option("--button", "-b", type=str, default="left", help="Mouse button (left/right/middle)")
@click.option("--after-sleep", type=float, default=0, help="Sleep time after click (seconds)")
@click.option("--cid", "--connection-id", help="Connection ID to use (default: latest)")
def click_rel(x: float, y: float, button: str, after_sleep: float, cid: Optional[str]):
    """Click at relative coordinates (0-1)."""
    if button not in {"left", "right", "middle"}:
        print(_error("button must be one of: left, right, middle"))
        sys.exit(1)
    if not 0 <= x <= 1 or not 0 <= y <= 1:
        print(_error("relative coordinates must be between 0 and 1"))
        sys.exit(1)
    _dispatch("click_rel", {"x": x, "y": y, "button": button, "after_sleep": after_sleep}, cid)


@cli.command()
@click.option("--fx", type=int, required=True, help="From X coordinate")
@click.option("--fy", type=int, required=True, help="From Y coordinate")
@click.option("--tx", type=int, required=True, help="To X coordinate")
@click.option("--ty", type=int, required=True, help="To Y coordinate")
@click.option("--duration", type=float, default=0.5, help="Swipe duration (seconds)")
@click.option("--after-sleep", type=float, default=0.1, help="Settle time after swipe (seconds)")
@click.option("--cid", "--connection-id", help="Connection ID to use (default: latest)")
def swipe(fx: int, fy: int, tx: int, ty: int, duration: float, after_sleep: float, cid: Optional[str]):
    """Swipe gesture."""
    _dispatch(
        "swipe", {"fx": fx, "fy": fy, "tx": tx, "ty": ty, "duration": duration, "after_sleep": after_sleep}, cid
    )


@cli.command()
@click.option("--x", type=int, required=True, help="X coordinate")
@click.option("--y", type=int, required=True, help="Y coordinate")
@click.option("--amount", type=int, required=True, help="Scroll amount (positive for up, negative for down)")
@click.option("--cid", "--connection-id", help="Connection ID to use (default: latest)")
def scroll(x: int, y: int, amount: int, cid: Optional[str]):
    """Scroll at position."""
    _dispatch("scroll", {"x": x, "y": y, "amount": amount}, cid)


@cli.command(name="key")
@click.option("--key", "-k", type=str, required=True, help="Key to press (enter/esc/f1/...)")
@click.option("--down-time", type=float, default=0.02, help="Key down time (seconds)")
@click.option("--cid", "--connection-id", help="Connection ID to use (default: latest)")
def do_key(key: str, down_time: float, cid: Optional[str]):
    """Press keyboard key."""
    _dispatch("key", {"key": key, "down_time": down_time}, cid)


@cli.command()
@click.option("--content", "-c", type=str, required=True, help="Text to type")
@click.option("--cid", "--connection-id", help="Connection ID to use (default: latest)")
def text(content: str, cid: Optional[str]):
    """Type text."""
    _dispatch("text", {"content": content}, cid)


@cli.command()
@click.option("--region", "-r", type=int, nargs=4, help="Region to OCR (x y w h), optional")
@click.option("--cid", "--connection-id", help="Connection ID to use (default: latest)")
def ocr(region: Optional[tuple], cid: Optional[str]):
    """Recognize text."""
    params = {"region": list(region) if region else None}
    _dispatch("ocr", params, cid)


@cli.command()
@click.option("--template", "-t", type=str, required=True, help="Template image path")
@click.option("--threshold", "-th", type=float, default=0.8, help="Confidence threshold (0-1)")
@click.option("--cid", "--connection-id", help="Connection ID to use (default: latest)")
def find_image(template: str, threshold: float, cid: Optional[str]):
    """Find image on screen (template matching)."""
    _dispatch("find_image", {"template": template, "threshold": threshold}, cid)


@cli.command()
@click.option("--hex", type=str, required=True, help="Color in hex format (RRGGBB)")
@click.option("--threshold", type=float, default=0.1, help="Color tolerance (0-1)")
@click.option("--cid", "--connection-id", help="Connection ID to use (default: latest)")
def find_color(hex: str, threshold: float, cid: Optional[str]):
    """Find color region on screen."""
    _dispatch("find_color", {"hex": hex, "threshold": threshold}, cid)


if __name__ == "__main__":
    cli()
