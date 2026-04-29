#!/usr/bin/env python3
"""Smoke tests for ok-cli."""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def run_command(cmd_args, expect_json=True):
    """Run ok-cli and optionally parse its JSON output."""
    result = subprocess.run(
        [sys.executable, "-m", "ok.cli"] + cmd_args,
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=90,
    )
    parsed = None
    if expect_json:
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"Expected JSON output, got: {result.stdout!r}\nSTDERR: {result.stderr}") from exc
    return result, parsed


def assert_json_failure(cmd_args):
    result, payload = run_command(cmd_args)
    assert result.returncode != 0, f"Expected failure for {cmd_args}, got return code 0"
    assert payload["success"] is False, payload
    assert payload.get("error"), payload
    return payload


def assert_json_success(cmd_args):
    result, payload = run_command(cmd_args)
    assert result.returncode == 0, f"Command failed: {cmd_args}\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    assert payload["success"] is True, payload
    return payload


def main():
    parser = argparse.ArgumentParser(description="Run ok-cli smoke tests.")
    parser.add_argument("--live", action="store_true", help="Run commands that start a desktop daemon")
    args = parser.parse_args()

    print("=== Testing ok-cli ===")

    print("\n1. Testing help command:")
    help_result, _ = run_command(["--help"], expect_json=False)
    assert help_result.returncode == 0, help_result.stderr
    assert "Usage:" in help_result.stdout, help_result.stdout
    print("Help command works.")

    print("\n2. Testing screen-info command (before connect):")
    payload = assert_json_failure(["screen-info"])
    print(f"Expected failure: {payload['error']}")

    print("\n3. Testing list-connections JSON output:")
    list_payload = assert_json_success(["list-connections"])
    assert "connections" in list_payload["data"], list_payload
    print("list-connections returns JSON.")

    if not args.live:
        print("\nSkipping live desktop daemon flow. Use --live to test connect/screenshot/disconnect.")
        print("\n=== Smoke tests completed ===")
        return 0

    connection_id = None
    try:
        print("\n4. Testing connect to desktop:")
        connect_payload = assert_json_success(["connect", "--desktop"])
        connection_id = connect_payload["data"]["connection_id"]
        print(f"Connected successfully: {connection_id}")

        print("\n5. Testing screen-info after connect:")
        screen_payload = assert_json_success(["screen-info", "--cid", connection_id])
        screen_data = screen_payload["data"]
        assert screen_data["width"] > 0 and screen_data["height"] > 0, screen_data
        print(f"Screen resolution: {screen_data['width']}x{screen_data['height']}")

        print("\n6. Testing screenshot:")
        output_path = Path(tempfile.gettempdir()) / "ok_cli_smoke.png"
        screenshot_payload = assert_json_success(["screenshot", "--cid", connection_id, "--output", str(output_path)])
        assert output_path.exists(), screenshot_payload
        assert screenshot_payload["data"]["width"] > 0 and screenshot_payload["data"]["height"] > 0
        print(f"Screenshot saved to {output_path}")
    finally:
        if connection_id:
            print("\n7. Testing disconnect:")
            disconnect_payload = assert_json_success(["disconnect", "--cid", connection_id])
            assert disconnect_payload["data"]["connection_id"] == connection_id, disconnect_payload
            print("Disconnected successfully.")

    print("\n=== All tests completed ===")
    return 0

if __name__ == "__main__":
    sys.exit(main())
