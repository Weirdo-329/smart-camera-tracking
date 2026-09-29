"""缩放控制模块 — 键盘控制 + 触控双指缩放（需内核支持 HID_MULTITOUCH）"""

import struct
import threading
import cv2


class ZoomController:
    def __init__(self, device_path=None):
        self.zoom_level = 1.0
        self.zoom_center = None  # (x, y) 画面坐标，None 表示画面中心
        self._zoom_step = 0.5

        # 触控相关
        self._device_path = device_path
        self._running = False
        self._thread = None
        self._slots = {0: {"id": -1, "x": 0, "y": 0}, 1: {"id": -1, "x": 0, "y": 0}}
        self._current_slot = 0
        self._pinch_start_dist = None
        self._pinch_start_zoom = 1.0
        self.screen_w = 1920
        self.screen_h = 1080

    def start_touch(self):
        """启动触控监听（需内核支持多点触控）。"""
        if not self._device_path:
            return False
        self._running = True
        self._thread = threading.Thread(target=self._read_touch_events, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)

    def handle_key(self, key):
        """
        处理按键，返回 True 表示已处理。
        支持: +/= 放大, - 缩小, 0 重置
        """
        if key in (ord("+"), ord("="), 43, 61):  # + 或 =
            self.zoom_level = min(5.0, self.zoom_level + self._zoom_step)
            return True
        elif key in (ord("-"), 45):  # -
            self.zoom_level = max(1.0, self.zoom_level - self._zoom_step)
            if self.zoom_level <= 1.0:
                self.zoom_center = None
            return True
        elif key == ord("0"):  # 重置
            self.zoom_level = 1.0
            self.zoom_center = None
            return True
        return False

    def apply_zoom(self, frame):
        """对画面应用缩放，返回缩放后的画面。"""
        if self.zoom_level <= 1.0:
            return frame

        h, w = frame.shape[:2]

        if self.zoom_center:
            cx, cy = self.zoom_center
        else:
            cx, cy = w // 2, h // 2

        cx = max(0, min(w, cx))
        cy = max(0, min(h, cy))

        new_w = int(w / self.zoom_level)
        new_h = int(h / self.zoom_level)

        x1 = max(0, cx - new_w // 2)
        y1 = max(0, cy - new_h // 2)
        x2 = min(w, x1 + new_w)
        y2 = min(h, y1 + new_h)

        if x2 - x1 < new_w:
            x1 = max(0, x2 - new_w)
        if y2 - y1 < new_h:
            y1 = max(0, y2 - new_h)

        cropped = frame[y1:y2, x1:x2]
        if cropped.size == 0:
            return frame
        return cv2.resize(cropped, (w, h), interpolation=cv2.INTER_LINEAR)

    # ---- 触控部分（内核需支持 HID_MULTITOUCH）----

    def _read_touch_events(self):
        EVENT_FORMAT = "llHHI"
        EVENT_SIZE = struct.calcsize(EVENT_FORMAT)
        try:
            with open(self._device_path, "rb") as f:
                while self._running:
                    data = f.read(EVENT_SIZE)
                    if not data or len(data) < EVENT_SIZE:
                        continue
                    _, _, ev_type, code, value = struct.unpack(EVENT_FORMAT, data)
                    self._handle_touch_event(ev_type, code, value)
        except Exception as e:
            print(f"[ZoomController] 触控读取失败: {e}")

    def _handle_touch_event(self, ev_type, code, value):
        if ev_type != 3:  # EV_ABS
            return
        slot = self._slots[self._current_slot]
        if code == 47:  # ABS_MT_SLOT
            self._current_slot = value if value in (0, 1) else 0
        elif code == 57:  # ABS_MT_TRACKING_ID
            slot["id"] = value
            if value == -1:
                self._pinch_start_dist = None
        elif code == 53:  # ABS_MT_POSITION_X
            slot["x"] = value
        elif code == 54:  # ABS_MT_POSITION_Y
            slot["y"] = value
        elif code == 0:  # SYN_REPORT
            self._process_pinch()

    def _process_pinch(self):
        s0, s1 = self._slots[0], self._slots[1]
        if s0["id"] == -1 or s1["id"] == -1:
            return
        dx = s1["x"] - s0["x"]
        dy = s1["y"] - s0["y"]
        dist = (dx * dx + dy * dy) ** 0.5
        cx = (s0["x"] + s1["x"]) // 2
        cy = (s0["y"] + s1["y"]) // 2
        self.zoom_center = (int(cx * 1280 / self.screen_w), int(cy * 720 / self.screen_h))
        if self._pinch_start_dist is None:
            self._pinch_start_dist = dist
            self._pinch_start_zoom = self.zoom_level
            return
        if dist > 0:
            scale = dist / self._pinch_start_dist
            self.zoom_level = max(1.0, min(5.0, self._pinch_start_zoom * scale))
