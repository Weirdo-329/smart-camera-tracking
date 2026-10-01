"""智能跟踪器 — YOLO 检测 + 框选锁定 + 轻量跟踪器接力"""

import cv2
import numpy as np
import time
from dataclasses import dataclass
from typing import Optional
from PIL import Image, ImageDraw, ImageFont
import config
from npu_detector import NpuDetector

# 中文字体（文泉驿正黑）
_CJK_FONT_PATH = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
_cjk_font_cache = {}


def _get_cjk_font(size):
    """获取中文字体（缓存）。"""
    if size not in _cjk_font_cache:
        try:
            _cjk_font_cache[size] = ImageFont.truetype(_CJK_FONT_PATH, size)
        except (OSError, IOError):
            _cjk_font_cache[size] = ImageFont.load_default()
    return _cjk_font_cache[size]


def _draw_chinese(frame, text, center, font_size, text_color=(255, 255, 255),
                  anchor="center"):
    """在 OpenCV 帧上绘制中文文字（PIL 渲染）。anchor: center / left。"""
    font = _get_cjk_font(font_size)
    # PIL 渲染文字
    img_pil = Image.new("RGBA", (800, font_size + 10), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img_pil)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((5 - bbox[0], 5 - bbox[1]), text, font=font, fill=text_color + (255,))
    # 转 OpenCV 格式并贴到帧上
    img_cv = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGBA2BGRA)
    if anchor == "left":
        x1 = int(center[0])
    else:
        x1 = int(center[0] - tw / 2) - 5
    y1 = int(center[1] - th / 2) - 5
    x1 = max(0, x1)
    y1 = max(0, y1)
    fh, fw = frame.shape[:2]
    if x1 >= fw or y1 >= fh:
        return
    x2 = min(fw, x1 + img_cv.shape[1])
    y2 = min(fh, y1 + img_cv.shape[0])
    roi = frame[y1:y2, x1:x2]
    overlay = img_cv[:y2 - y1, :x2 - x1]
    # 按 alpha 混合
    alpha = overlay[:, :, 3:4] / 255.0
    roi[:] = (overlay[:, :, :3] * alpha + roi * (1 - alpha)).astype(np.uint8)


@dataclass
class TrackingResult:
    has_target: bool
    target_bbox: Optional[tuple]   # (x, y, w, h) 锁定目标的边界框
    target_center: Optional[tuple] # (cx, cy)
    target_class: str              # 目标类别名
    offset_dx: int
    offset_dy: int
    detections: list               # 当前帧所有 YOLO 检测结果
    tracking_state: str            # "detecting" / "tracking" / "lost"


class SmartTracker:
    def __init__(self):
        # NPU 检测器（YOLOv5，板载 NPU 加速推理）
        self.detector = NpuDetector(conf=config.DETECT_CONFIDENCE)

        # OpenCV 轻量跟踪器
        self._tracker = None
        self._target_bbox = None       # (x, y, w, h)
        self._target_class = ""
        self._tracking = False

        # 检测/跟踪状态
        self._frame_count = 0
        self._last_detections = []
        self._lost_count = 0
        self._max_lost = 15            # KCF 连续失败 N 帧后放弃

        # 遮挡处理
        self._target_lost = False      # 目标疑似被遮挡
        self._lost_frames = 0          # 遮挡持续帧数
        self._reacquire_timeout = 150  # 遮挡超过 N 帧自动取消跟踪（约10秒）
        self._verify_fail_count = 0    # 连续校验失败次数
        self._verify_fail_threshold = 4  # 连续失败 N 个检测周期才判定遮挡

        # 框选状态
        self._drawing = False
        self._draw_start = None
        self._draw_end = None

        # 取消跟踪按钮区域（画面坐标）
        self._cancel_btn_rect = None

        # 手动模式方向按钮区域 {"up": (x1,y1,x2,y2), ...}
        self._dir_btn_rects = {}

        # 缩放按钮区域 {"in": ..., "out": ...}
        self._zoom_btn_rects = {}

        # 退出按钮区域
        self._exit_btn_rect = None

        # 手动控制回调（main.py 绑定到 servo.step_move）
        self.manual_move_callback = None

        # 缩放回调（main.py 绑定到 zoom 控制）
        self.zoom_callback = None

        # 退出回调（main.py 绑定，等效按 q 键）
        self.exit_callback = None

        # 当前模式: "manual" / "auto"
        self.mode = "manual"

    def select_by_click(self, x, y):
        """点击选择：在最近一次检测结果中找到包含点击位置的目标。"""
        for d in self._last_detections:
            bx, by, bw, bh = d["bbox"]
            if bx <= x <= bx + bw and by <= y <= by + bh:
                self._lock_target(d["bbox"], d["class_name"])
                return True
        return False

    def select_by_index(self, index):
        """按编号选择（键盘 1-9）。"""
        if 0 <= index < len(self._last_detections):
            d = self._last_detections[index]
            self._lock_target(d["bbox"], d["class_name"])
            return True
        return False

    def select_by_bbox(self, bbox):
        """手动框选目标。"""
        self._lock_target(bbox, "Custom")

    def clear_target(self):
        """清除锁定目标，切回手动模式。"""
        self._tracker = None
        self._target_bbox = None
        self._tracking = False
        self._target_class = ""
        self._lost_count = 0
        self._target_lost = False
        self._lost_frames = 0
        self._verify_fail_count = 0
        self.mode = "manual"
        print("[SmartTracker] 已取消跟踪，切换到手动模式")

    def _lock_target(self, bbox, class_name):
        """初始化跟踪器并锁定目标，进入自动模式。"""
        x, y, w, h = bbox
        # 确保 bbox 在画面范围内
        x = max(0, x)
        y = max(0, y)
        w = min(w, config.CAMERA_WIDTH - x)
        h = min(h, config.CAMERA_HEIGHT - y)
        if w < 10 or h < 10:
            return

        self._target_bbox = (x, y, w, h)
        self._target_class = class_name
        self._tracking = True
        self._lost_count = 0
        self.mode = "auto"
        print(f"[SmartTracker] 锁定目标: {class_name} at ({x},{y}) {w}x{h}，进入自动模式")

    def _create_tracker(self):
        """创建 OpenCV 跟踪器（KCF 最快）。"""
        try:
            return cv2.TrackerKCF.create()
        except AttributeError:
            pass
        try:
            return cv2.legacy.TrackerKCF_create()
        except AttributeError:
            pass
        return cv2.TrackerCSRT.create()

    def update(self, frame):
        """执行一帧跟踪，返回 TrackingResult。"""
        self._frame_count += 1

        # --- 阶段 1：NPU 目标检测（手动模式定期运行，提供可点击的检测框）---
        if not self._tracking and config.AUTO_DETECT_ENABLE:
            if self._frame_count % config.DETECT_INTERVAL == 0 or not self._last_detections:
                self._last_detections = self.detector.detect(frame)
        else:
            # 跟踪中不运行检测，节省 NPU 算力
            self._last_detections = []

        # --- 阶段 2：跟踪 ---
        if self._tracking and self._target_bbox is not None:
            # 缩小画面跟踪（加速 KCF）
            track_scale = 0.5  # 在 640x360 上跟踪
            small_frame = cv2.resize(frame, None, fx=track_scale, fy=track_scale)
            sx, sy = track_scale, track_scale

            # 初始化跟踪器
            if self._tracker is None:
                x, y, w, h = self._target_bbox
                small_bbox = (int(x*sx), int(y*sy), int(w*sx), int(h*sy))
                self._tracker = self._create_tracker()
                self._tracker.init(small_frame, small_bbox)

            # 每 2 帧更新一次
            if self._frame_count % 2 == 0:
                ok, bbox = self._tracker.update(small_frame)
            else:
                ok = True
                x, y, w, h = self._target_bbox
                bbox = (int(x*sx), int(y*sy), int(w*sx), int(h*sy))

            if ok:
                sx_bx, sx_by, sx_bw, sx_bh = [int(v) for v in bbox]
                # 缩放回原始分辨率
                self._target_bbox = (
                    int(sx_bx / sx), int(sx_by / sy),
                    int(sx_bw / sx), int(sx_bh / sy),
                )
                self._lost_count = 0
                x, y, w, h = self._target_bbox
                cx = x + w // 2
                cy = y + h // 2
                dx = cx - config.FRAME_CENTER_X
                dy = cy - config.FRAME_CENTER_Y

                return TrackingResult(
                    has_target=True,
                    target_bbox=self._target_bbox,
                    target_center=(cx, cy),
                    target_class=self._target_class,
                    offset_dx=dx,
                    offset_dy=dy,
                    detections=self._last_detections,
                    tracking_state="tracking",
                )
            else:
                self._lost_count += 1
                if self._lost_count > self._max_lost:
                    print("[SmartTracker] 目标丢失，等待重新检测")
                    self.clear_target()

        # --- 阶段 3：没有目标 ---
        return TrackingResult(
            has_target=False,
            target_bbox=None,
            target_center=None,
            target_class="",
            offset_dx=0,
            offset_dy=0,
            detections=self._last_detections,
            tracking_state="detecting",
        )

    def draw(self, frame, result, scale=1.0):
        """
        内容层：检测框、目标框、箭头、中心十字。
        scale: 绘制缩放系数（1080p 推流时 = capture/process 分辨率比）。
        """
        # 未锁定：绘制 NPU 检测框（带编号，可点击锁定）
        if not result.has_target:
            for i, d in enumerate(result.detections):
                bx = int(d["bbox"][0] * scale)
                by = int(d["bbox"][1] * scale)
                bw = int(d["bbox"][2] * scale)
                bh = int(d["bbox"][3] * scale)
                cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), (0, 255, 0), 2)
                label = f"[{i+1}] {d['class_name']} {d['conf']:.0%}"
                (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                cv2.rectangle(frame, (bx, by - th - 6), (bx + tw, by), (0, 255, 0), -1)
                cv2.putText(frame, label, (bx, by - 4),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

        # 绘制锁定目标
        if result.has_target and result.target_bbox:
            x = int(result.target_bbox[0] * scale)
            y = int(result.target_bbox[1] * scale)
            w = int(result.target_bbox[2] * scale)
            h = int(result.target_bbox[3] * scale)
            cx = int(result.target_center[0] * scale)
            cy = int(result.target_center[1] * scale)

            # 锁定框（红色粗框）
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 0, 255), 3)

            # 中心点
            cv2.circle(frame, (cx, cy), 6, (0, 0, 255), -1)

            # 偏移箭头
            fc = (int(config.FRAME_CENTER_X * scale), int(config.FRAME_CENTER_Y * scale))
            cv2.arrowedLine(frame, (cx, cy), fc, (0, 0, 255), 2, tipLength=0.15)

            # 锁定标签
            label = f"LOCKED: {result.target_class}"
            cv2.putText(frame, label, (x, y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

            # 偏移量
            cv2.putText(
                frame,
                f"dx:{result.offset_dx} dy:{result.offset_dy}",
                (cx + 15, cy + 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2,
            )

        # 框选过程中画矩形（仅本地 720p 画面，scale=1 时）
        if scale == 1.0 and self._drawing and self._draw_start and self._draw_end:
            cv2.rectangle(frame, self._draw_start, self._draw_end, (255, 255, 0), 2)

        return frame

    def draw_ui(self, frame, result):
        """UI 层：按钮、模式标签（缩放后绘制，固定在屏幕上）。"""
        # 中心准心（UI 层绘制，大小不随缩放变化）
        fc = (config.FRAME_CENTER_X, config.FRAME_CENTER_Y)
        cv2.drawMarker(frame, fc, (255, 255, 255), cv2.MARKER_CROSS, 20, 2)

        # 取消跟踪按钮（右上角）
        self._draw_cancel_button(frame, result)

        # 缩放按钮（左上角，状态文字下方）
        self._draw_zoom_buttons(frame)

        # 退出按钮（左上角，缩放按钮下方）
        self._draw_exit_button(frame)

        # 手动模式：绘制方向控制按钮
        if self.mode == "manual":
            self._draw_dir_buttons(frame)

        return frame

    def _draw_zoom_buttons(self, frame):
        """左上角 放大/缩小 按钮。"""
        bw, bh = 80, 55
        bx1, by1 = 15, 100
        gap = 15

        self._zoom_btn_rects = {}
        for name, text, y in [("in", "放大", by1), ("out", "缩小", by1 + bh + gap)]:
            # 半透明背景 + 边框
            overlay = frame.copy()
            cv2.rectangle(overlay, (bx1, y), (bx1 + bw, y + bh), (60, 60, 60), -1)
            cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)
            cv2.rectangle(frame, (bx1, y), (bx1 + bw, y + bh), (200, 200, 200), 2)
            _draw_chinese(frame, text, (bx1 + bw // 2, y + bh // 2), 26, (255, 255, 255))
            self._zoom_btn_rects[name] = (bx1, y, bx1 + bw, y + bh)

    def _draw_exit_button(self, frame):
        """左上角 退出 按钮（红色，终止程序）。"""
        bw, bh = 80, 55
        bx1 = 15
        by1 = 240

        # 红色半透明背景 + 边框
        overlay = frame.copy()
        cv2.rectangle(overlay, (bx1, by1), (bx1 + bw, by1 + bh), (80, 30, 30), -1)
        cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)
        cv2.rectangle(frame, (bx1, by1), (bx1 + bw, by1 + bh), (255, 100, 100), 2)
        _draw_chinese(frame, "退出", (bx1 + bw // 2, by1 + bh // 2), 26, (255, 255, 255))
        self._exit_btn_rect = (bx1, by1, bx1 + bw, by1 + bh)

    def _draw_dir_buttons(self, frame):
        """手动模式方向按钮（左下角十字布局，远离边缘防裁剪）。"""
        fh, fw = frame.shape[:2]
        bs = 70                    # 按钮边长
        gap = 15                   # 按钮间距
        # 十字布局中心点（左下区域，距边缘留 150px 以上）
        ccx = 230
        ccy = fh - 230

        layout = {
            "up":    (ccx - bs // 2, ccy - bs - gap // 2 - bs // 2),
            "left":  (ccx - bs - gap // 2 - bs // 2, ccy - bs // 2),
            "right": (ccx + gap // 2 + bs // 2, ccy - bs // 2),
            "down":  (ccx - bs // 2, ccy + gap // 2 + bs // 2),
        }
        labels = {"up": "上", "down": "下", "left": "左", "right": "右"}

        self._dir_btn_rects = {}
        for direction, (bx, by) in layout.items():
            bx, by = int(bx), int(by)
            # 半透明背景 + 边框
            overlay = frame.copy()
            cv2.rectangle(overlay, (bx, by), (bx + bs, by + bs), (100, 100, 100), -1)
            cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)
            cv2.rectangle(frame, (bx, by), (bx + bs, by + bs), (200, 200, 200), 2)

            # 箭头文字
            _draw_chinese(frame, labels[direction],
                          (bx + bs // 2, by + bs // 2), 32, (255, 255, 255))

            self._dir_btn_rects[direction] = (bx, by, bx + bs, by + bs)

        # 模式标签
        _draw_chinese(frame, "手动模式", (ccx, ccy - bs - gap - 40), 22, (255, 255, 0))

    def _draw_cancel_button(self, frame, result):
        """绘制右上角取消跟踪按钮，返回按钮区域 (x1, y1, x2, y2)。"""
        fw = frame.shape[1]
        bw, bh = 150, 50
        bx1 = fw - bw - 15
        by1 = 15
        bx2 = bx1 + bw
        by2 = by1 + bh

        # 锁定状态显示红色按钮，未锁定显示灰色
        if result.has_target:
            color = (0, 0, 255)       # 红色填充
            text_color = (255, 255, 255)
            text = "取消跟踪"
        else:
            color = (90, 90, 90)      # 灰色
            text_color = (180, 180, 180)
            text = "未跟踪"

        # 按钮背景 + 边框
        cv2.rectangle(frame, (bx1, by1), (bx2, by2), color, -1)
        cv2.rectangle(frame, (bx1, by1), (bx2, by2), (255, 255, 255), 2)
        # 中文文字（PIL 渲染）
        _draw_chinese(frame, text, ((bx1 + bx2) // 2, (by1 + by2) // 2), 26, text_color)

        # 保存按钮区域供点击检测
        self._cancel_btn_rect = (bx1, by1, bx2, by2)

    @staticmethod
    def _is_same_bbox(b1, b2, threshold=30):
        """判断两个 bbox 是否大致相同。"""
        if b1 is None or b2 is None:
            return False
        return (abs(b1[0] - b2[0]) < threshold and
                abs(b1[1] - b2[1]) < threshold and
                abs(b1[2] - b2[2]) < threshold and
                abs(b1[3] - b2[3]) < threshold)

    def _is_on_cancel_button(self, x, y):
        """判断坐标是否在取消跟踪按钮上。"""
        rect = getattr(self, "_cancel_btn_rect", None)
        if rect is None:
            return False
        bx1, by1, bx2, by2 = rect
        return bx1 <= x <= bx2 and by1 <= y <= by2

    def handle_mouse(self, event, x, y, flags, param):
        """鼠标回调：方向按钮 / 点击选择 / 框选 / 按钮取消锁定。"""
        if event == cv2.EVENT_LBUTTONDOWN:
            # 优先判断取消跟踪按钮
            if self._is_on_cancel_button(x, y):
                if self._tracking:
                    print("[SmartTracker] 按钮取消跟踪")
                    self.clear_target()
                return

            # 缩放按钮（放大/缩小）
            for name, rect in self._zoom_btn_rects.items():
                rx1, ry1, rx2, ry2 = rect
                if rx1 <= x <= rx2 and ry1 <= y <= ry2:
                    if self.zoom_callback:
                        self.zoom_callback(name)
                    return

            # 退出按钮（终止程序，等效按 q）
            if self._exit_btn_rect is not None:
                rx1, ry1, rx2, ry2 = self._exit_btn_rect
                if rx1 <= x <= rx2 and ry1 <= y <= ry2:
                    print("[SmartTracker] 退出按钮被点击")
                    if self.exit_callback:
                        self.exit_callback()
                    return

            # 手动模式：方向按钮控制云台
            if self.mode == "manual":
                for direction, rect in self._dir_btn_rects.items():
                    rx1, ry1, rx2, ry2 = rect
                    if rx1 <= x <= rx2 and ry1 <= y <= ry2:
                        if self.manual_move_callback:
                            self.manual_move_callback(direction)
                        else:
                            print(f"[手动模式] {direction}")
                        return

            if self._tracking:
                # 已锁定状态：点击空白处取消锁定
                if not self.select_by_click(x, y):
                    self.clear_target()
            else:
                # 未锁定状态：点击检测框锁定，否则开始框选
                if not self.select_by_click(x, y):
                    self._drawing = True
                    self._draw_start = (x, y)
                    self._draw_end = (x, y)

        elif event == cv2.EVENT_MOUSEMOVE and self._drawing:
            self._draw_end = (x, y)

        elif event == cv2.EVENT_LBUTTONUP and self._drawing:
            self._drawing = False
            if self._draw_start and self._draw_end:
                x1 = min(self._draw_start[0], self._draw_end[0])
                y1 = min(self._draw_start[1], self._draw_end[1])
                x2 = max(self._draw_start[0], self._draw_end[0])
                y2 = max(self._draw_start[1], self._draw_end[1])
                w, h = x2 - x1, y2 - y1
                if w > 20 and h > 20:
                    self.select_by_bbox((x1, y1, w, h))

        elif event == cv2.EVENT_RBUTTONDOWN:
            self.clear_target()

    def release(self):
        pass
