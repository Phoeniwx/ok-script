"""Daemon process for persistent ok-cli connections."""

import json
import logging
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict

# Disable QFluentWidgets tip message and skip mutex check
os.environ["DISABLE_QFluentWidgets_TIPS"] = "1"
os.environ["OK_CLI_DAEMON"] = "1"

import cv2

from ok.cli.state import ConnectionManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.NullHandler()],
)


class DaemonHandler(BaseHTTPRequestHandler):
    ok_instance: Any = None
    conn_id: str = ""
    connection_info: Dict[str, Any] = {}
    init_error: str = ""
    ready_event = threading.Event()
    shutdown_event = threading.Event()

    def log_message(self, format, *args):
        pass

    def do_POST(self):
        if self.path != "/command":
            self.send_error(404)
            return

        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            req = json.loads(body.decode("utf-8"))
        except Exception:
            self.send_error(400)
            return

        cmd = req.get("cmd", "")
        params = req.get("params", {})

        try:
            result = self._handle_command(cmd, params)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "data": result}, ensure_ascii=False).encode("utf-8"))
        except Exception as e:
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                json.dumps({"success": False, "error": str(e)}, ensure_ascii=False).encode("utf-8")
            )

    def _screen_size(self):
        dm = self.ok_instance.device_manager
        cap = dm.capture_method
        if cap is not None:
            width = getattr(cap, "width", 0) or 0
            height = getattr(cap, "height", 0) or 0
            if width and height:
                return width, height
        preferred = dm.get_preferred_device() if hasattr(dm, "get_preferred_device") else None
        if preferred:
            return preferred.get("width", 0) or 0, preferred.get("height", 0) or 0
        hwnd_window = getattr(dm, "hwnd_window", None)
        return getattr(hwnd_window, "width", 0) or 0, getattr(hwnd_window, "height", 0) or 0

    def _input_size(self):
        dm = self.ok_instance.device_manager
        hwnd_window = getattr(dm, "hwnd_window", None)
        hwnd = getattr(hwnd_window, "hwnd", 0) if hwnd_window else 0
        if hwnd:
            try:
                import win32gui

                left, top, right, bottom = win32gui.GetClientRect(hwnd)
                width = right - left
                height = bottom - top
                if width > 0 and height > 0:
                    scaling = float(getattr(hwnd_window, "scaling", 1) or 1)
                    if scaling > 1:
                        return int(round(width / scaling)), int(round(height / scaling))
                    return width, height
            except Exception:
                pass
        return self._screen_size()

    def _to_input_coords(self, x, y):
        capture_width, capture_height = self._screen_size()
        input_width, input_height = self._input_size()
        if capture_width <= 0 or capture_height <= 0 or input_width <= 0 or input_height <= 0:
            return int(x), int(y)
        return (
            int(round(float(x) * input_width / capture_width)),
            int(round(float(y) * input_height / capture_height)),
        )

    def _to_virtual_screen_coords(self, x, y):
        dm = self.ok_instance.device_manager
        hwnd_window = getattr(dm, "hwnd_window", None)
        hwnd = getattr(hwnd_window, "hwnd", 0) if hwnd_window else 0
        input_x, input_y = self._to_input_coords(x, y)
        if hwnd:
            try:
                import win32gui

                origin_x, origin_y = win32gui.ClientToScreen(hwnd, (0, 0))
                scaling = float(getattr(hwnd_window, "scaling", 1) or 1)
                if scaling > 1:
                    origin_x = int(round(origin_x / scaling))
                    origin_y = int(round(origin_y / scaling))
                return origin_x + input_x, origin_y + input_y
            except Exception:
                pass
        return input_x, input_y

    def _dpi_unaware_click(self, x, y, button):
        import ctypes
        import win32api
        import win32con

        screen_x, screen_y = self._to_virtual_screen_coords(x, y)
        button_events = {
            "left": (win32con.MOUSEEVENTF_LEFTDOWN, win32con.MOUSEEVENTF_LEFTUP),
            "right": (win32con.MOUSEEVENTF_RIGHTDOWN, win32con.MOUSEEVENTF_RIGHTUP),
            "middle": (win32con.MOUSEEVENTF_MIDDLEDOWN, win32con.MOUSEEVENTF_MIDDLEUP),
        }
        down_event, up_event = button_events.get(button, button_events["left"])
        previous_context = ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-1))
        try:
            win32api.SetCursorPos((screen_x, screen_y))
            win32api.mouse_event(down_event, screen_x, screen_y, 0, 0)
            time.sleep(0.05)
            win32api.mouse_event(up_event, screen_x, screen_y, 0, 0)
        finally:
            if previous_context:
                ctypes.windll.user32.SetThreadDpiAwarenessContext(previous_context)
        return screen_x, screen_y

    def _require_capture(self):
        if self.init_error:
            raise RuntimeError(self.init_error)
        dm = self.ok_instance.device_manager
        cap = dm.capture_method
        if cap is None:
            raise RuntimeError("capture is not ready yet")
        return dm, cap

    def _require_interaction(self):
        dm, cap = self._require_capture()
        interaction = dm.interaction
        if interaction is None:
            raise RuntimeError("interaction is not ready yet")
        return dm, cap, interaction

    def _capture_frame(self, retries: int = 20):
        _, cap = self._require_capture()
        frame = None
        for _ in range(retries):
            frame = cap.get_frame()
            if frame is not None:
                return frame
            time.sleep(0.3)
        raise RuntimeError("Failed to capture frame")

    def _write_square_crop(self, frame, center_x, center_y, size, output):
        size = int(size)
        if size <= 0:
            raise RuntimeError("size must be greater than 0")

        frame_h, frame_w = frame.shape[:2]
        center_x = int(round(float(center_x)))
        center_y = int(round(float(center_y)))
        half = size // 2
        x1 = max(0, center_x - half)
        y1 = max(0, center_y - half)
        x2 = min(frame_w, x1 + size)
        y2 = min(frame_h, y1 + size)

        if x2 - x1 < size:
            x1 = max(0, x2 - size)
        if y2 - y1 < size:
            y1 = max(0, y2 - size)

        cropped = frame[y1:y2, x1:x2]
        if cropped.size == 0:
            raise RuntimeError("crop region is outside the screenshot")

        output_path = Path(output)
        if output_path.parent and str(output_path.parent) != ".":
            output_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(output, cropped)
        crop_h, crop_w = cropped.shape[:2]
        return {
            "path": output,
            "center_x": center_x,
            "center_y": center_y,
            "x": x1,
            "y": y1,
            "width": crop_w,
            "height": crop_h,
            "size": size,
            "screenshot_width": frame_w,
            "screenshot_height": frame_h,
        }

    def _handle_command(self, cmd: str, params: Dict) -> Dict:
        dm = self.ok_instance.device_manager

        if cmd == "ping":
            hwnd_window = getattr(dm, "hwnd_window", None)
            return {
                "status": "ok",
                "ready": self.ready_event.is_set(),
                "error": self.init_error,
                "hwnd": hwnd_window.hwnd if hwnd_window else 0,
            }

        elif cmd == "shutdown":
            type(self).shutdown_event.set()

            def force_exit():
                time.sleep(0.5)
                os._exit(0)

            threading.Thread(target=force_exit, daemon=True).start()
            return {"status": "shutting_down"}

        elif cmd == "screen_info":
            _, cap = self._require_capture()
            w, h = self._screen_size()
            if not w or not h:
                frame = self._capture_frame(retries=2)
                h, w = frame.shape[:2]
            mode = self.connection_info.get("mode", "unknown")
            cap_name = type(cap).__name__
            return {"width": w, "height": h, "mode": mode, "capture_method": cap_name}

        elif cmd == "screenshot":
            output = params.get("output", "screenshot.png")
            frame = self._capture_frame()
            output_path = Path(output)
            if output_path.parent and str(output_path.parent) != ".":
                output_path.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(output, frame)
            h, w = frame.shape[:2]
            return {"path": output, "width": w, "height": h}

        elif cmd == "crop":
            frame = self._capture_frame()
            output = params.get("output", "crop.png")
            return self._write_square_crop(
                frame,
                params.get("x", 0),
                params.get("y", 0),
                params.get("size", 80),
                output,
            )

        elif cmd == "crop_rel":
            frame = self._capture_frame()
            frame_h, frame_w = frame.shape[:2]
            output = params.get("output", "crop.png")
            return self._write_square_crop(
                frame,
                float(params.get("x", 0)) * frame_w,
                float(params.get("y", 0)) * frame_h,
                params.get("size", 80),
                output,
            )

        elif cmd == "click":
            self._require_interaction()
            x = params.get("x", 0)
            y = params.get("y", 0)
            button = params.get("button", "left")
            after_sleep = params.get("after_sleep", 0)
            screen_x, screen_y = self._dpi_unaware_click(x, y, button)
            if after_sleep > 0:
                time.sleep(after_sleep)
            input_x, input_y = self._to_input_coords(x, y)
            return {
                "x": x,
                "y": y,
                "button": button,
                "input_x": input_x,
                "input_y": input_y,
                "screen_x": screen_x,
                "screen_y": screen_y,
            }

        elif cmd == "click_rel":
            _, _, interaction = self._require_interaction()
            x = params.get("x", 0)
            y = params.get("y", 0)
            button = params.get("button", "left")
            after_sleep = params.get("after_sleep", 0)
            w, h = self._screen_size()
            if not w or not h:
                raise RuntimeError("screen size is not ready yet")
            abs_x = int(x * w)
            abs_y = int(y * h)
            screen_x, screen_y = self._dpi_unaware_click(abs_x, abs_y, button)
            if after_sleep > 0:
                time.sleep(after_sleep)
            input_x, input_y = self._to_input_coords(abs_x, abs_y)
            return {
                "x": x,
                "y": y,
                "abs_x": abs_x,
                "abs_y": abs_y,
                "button": button,
                "input_x": input_x,
                "input_y": input_y,
                "screen_x": screen_x,
                "screen_y": screen_y,
            }

        elif cmd == "swipe":
            _, _, interaction = self._require_interaction()
            fx = params.get("fx", 0)
            fy = params.get("fy", 0)
            tx = params.get("tx", 0)
            ty = params.get("ty", 0)
            duration = params.get("duration", 0.5)
            after_sleep = params.get("after_sleep", 0.1)
            duration_ms = max(float(duration) * 1000, 1)
            interaction.swipe(fx, fy, tx, ty, duration_ms, after_sleep=after_sleep)
            return {"fx": fx, "fy": fy, "tx": tx, "ty": ty, "duration": duration}

        elif cmd == "scroll":
            _, _, interaction = self._require_interaction()
            x = params.get("x", 0)
            y = params.get("y", 0)
            amount = params.get("amount", 0)
            interaction.scroll(x, y, amount)
            return {"x": x, "y": y, "amount": amount}

        elif cmd == "key":
            _, _, interaction = self._require_interaction()
            key = params.get("key", "")
            down_time = params.get("down_time", 0.02)
            interaction.send_key(key, down_time=down_time)
            return {"key": key}

        elif cmd == "text":
            _, _, interaction = self._require_interaction()
            content = params.get("content", "")
            interaction.input_text(content)
            return {"content": content}

        elif cmd == "ocr":
            region = params.get("region")
            frame = self._capture_frame()
            fs = self.ok_instance.feature_set
            if fs and hasattr(fs, "ocr_fun"):
                ocr_fn = fs.ocr_fun("default")
                x, y, w, h = region if region else (0, 0, frame.shape[1], frame.shape[0])
                from ok.feature.Box import Box

                box = Box(x, y, w, h, name="ocr_region")
                detected_boxes, _ = ocr_fn(box, frame, match=None, scale_factor=1.0, threshold=0.2, lib="default")
                all_text = " ".join(b.name for b in detected_boxes) if detected_boxes else ""
                boxes_list = [
                    {
                        "text": b.name,
                        "x": b.x,
                        "y": b.y,
                        "width": b.width,
                        "height": b.height,
                        "confidence": b.confidence,
                    }
                    for b in detected_boxes
                ] if detected_boxes else []
                return {"text": all_text, "boxes": boxes_list}
            raise RuntimeError("OCR is not available in the default CLI config. Provide an OK config with OCR/template_matching support before using this command.")

        elif cmd == "find_image":
            template_path = params.get("template", "")
            threshold = params.get("threshold", 0.8)
            template_img = cv2.imread(template_path)
            if template_img is None:
                raise RuntimeError(f"Failed to read template image: {template_path}")
            frame = self._capture_frame()
            result = cv2.matchTemplate(frame, template_img, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
            th, tw = template_img.shape[:2]
            if max_val >= threshold:
                return {"found": True, "x": max_loc[0], "y": max_loc[1], "width": tw, "height": th, "confidence": float(max_val)}
            return {"found": False, "confidence": float(max_val)}

        elif cmd == "find_color":
            import numpy as np

            hex_color = params.get("hex", "").lstrip("#")
            threshold = params.get("threshold", 0.1)
            if len(hex_color) != 6:
                raise RuntimeError("Invalid hex color format")
            r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
            tolerance = int(threshold * 255)
            lower = np.array([max(0, b - tolerance), max(0, g - tolerance), max(0, r - tolerance)])
            upper = np.array([min(255, b + tolerance), min(255, g + tolerance), min(255, r + tolerance)])
            frame = self._capture_frame()
            mask = cv2.inRange(frame, lower, upper)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            boxes = []
            for cnt in contours:
                bx, by, bw, bh = cv2.boundingRect(cnt)
                if bw > 5 and bh > 5:
                    boxes.append({"x": bx, "y": by, "width": bw, "height": bh})
            return {"color": params.get("hex", ""), "count": len(boxes), "boxes": boxes[:100]}

        else:
            raise RuntimeError(f"Unknown command: {cmd}")


def run_daemon(conn_id: str):
    from ok.util.logger import config_logger

    log_dir = ConnectionManager.BASE_DIR
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"daemon-{conn_id}.log"

    # Set up file handler for logging (will be added after config_logger)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    file_handler.setLevel(logging.INFO)

    config_logger({"debug": False})
    logger = logging.getLogger("ok-daemon")

    # Add file handler to root logger and specific loggers
    logging.getLogger().addHandler(file_handler)
    for logger_name in ["ok", "capture", "ok-daemon"]:
        logger = logging.getLogger(logger_name)
        logger.addHandler(file_handler)

    info = ConnectionManager.get_connection_info(conn_id)
    if not info:
        logger.error(f"Connection {conn_id} not found")
        sys.exit(1)

    config = info["config"]

    from ok import OK

    ok = OK(config)
    logger.info(f"OK instance created, checking hwnd_window")
    hwnd_window = ok.device_manager.hwnd_window
    logger.info(f"hwnd_window: {hwnd_window}, hwnd={hwnd_window.hwnd if hwnd_window else None}")

    # Start server immediately so CLI can poll
    DaemonHandler.ok_instance = ok
    DaemonHandler.conn_id = conn_id
    DaemonHandler.connection_info = info
    DaemonHandler.init_error = ""
    DaemonHandler.ready_event.clear()
    DaemonHandler.shutdown_event.clear()

    server = HTTPServer(("127.0.0.1", 0), DaemonHandler)
    port = server.server_address[1]

    ConnectionManager.update_daemon_info(conn_id, pid=os.getpid(), port=port)
    logger.info(f"Daemon started for {conn_id} on port {port}")

    import atexit

    cleanup_done = threading.Event()

    def cleanup():
        if cleanup_done.is_set():
            return
        cleanup_done.set()
        ConnectionManager.delete_connection(conn_id)
        if ok:
            try:
                if ok.device_manager and ok.device_manager.capture_method:
                    ok.device_manager.capture_method.close()
                if ok.device_manager and ok.device_manager.hwnd_window:
                    ok.device_manager.hwnd_window.stop()
                ok.quit()
            except Exception as exc:
                logger.exception("Daemon cleanup failed: %s", exc)
        logger.info(f"Daemon stopped for {conn_id}")

    atexit.register(cleanup)

    def shutdown_checker():
        DaemonHandler.shutdown_event.wait()
        server.shutdown()

    threading.Thread(target=shutdown_checker, daemon=True).start()

    def init_device():
        try:
            dm = ok.device_manager
            mode = info.get("mode")
            if mode == "window":
                dm.ensure_capture({"windows": config["windows"]})
                dm.do_start()
            else:
                dm.do_refresh()
                devices = [dev for dev in dm.get_devices() if dev.get("connected")]
                if devices:
                    target_device = max(devices, key=lambda dev: (dev.get("width", 0) or 0) * (dev.get("height", 0) or 0))
                    dm.set_preferred_device(target_device["imei"])
                elif dm.get_preferred_device() is None:
                    dm.set_preferred_device()
                dm.do_start()

            deadline = time.time() + 30
            last_error = "capture is not ready yet"
            while time.time() < deadline:
                cap = dm.capture_method
                if cap is not None:
                    try:
                        frame = cap.get_frame()
                        if frame is not None:
                            DaemonHandler.ready_event.set()
                            logger.info("Daemon device is ready")
                            return
                    except Exception as exc:
                        last_error = str(exc)
                time.sleep(0.5)
            raise RuntimeError(last_error)
        except Exception as exc:
            DaemonHandler.init_error = f"Failed to initialize device: {exc}"
            logger.exception(DaemonHandler.init_error)

    threading.Thread(target=init_device, daemon=True).start()
    try:
        server.serve_forever()
    finally:
        server.server_close()
        cleanup()
        os._exit(0)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m ok.cli.daemon <connection_id>")
        sys.exit(1)
    run_daemon(sys.argv[1])
