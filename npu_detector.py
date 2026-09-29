"""NPU 目标检测模块 — 调用板载 NPU 的 YOLOv5"""

import cv2
import subprocess
import os
import tempfile

YOLOV5_BIN = "/opt/yolov5/yolov5"
YOLOV5_MODEL = "/opt/yolov5/model/yolov5.nb"
YOLOV5_LIB = "/home/orangepi/.local/lib"

# COCO 80 类
COCO_CLASSES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
    "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench",
    "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
    "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove",
    "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup",
    "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
    "hair drier", "toothbrush",
]


class NpuDetector:
    def __init__(self, conf=0.4):
        self.conf = conf
        self._tmp_dir = tempfile.mkdtemp(prefix="npu_det_")
        self._tmp_input = os.path.join(self._tmp_dir, "input.jpg")
        self._tmp_output = os.path.join(self._tmp_dir, "result.png")

        # 验证文件存在
        if not os.path.exists(YOLOV5_BIN):
            raise FileNotFoundError(f"YOLOv5 binary not found: {YOLOV5_BIN}")
        if not os.path.exists(YOLOV5_MODEL):
            raise FileNotFoundError(f"YOLOv5 model not found: {YOLOV5_MODEL}")

    def detect(self, frame):
        """
        用 NPU 检测目标。

        参数:
            frame: BGR 图像

        返回:
            [{"center": (x, y), "bbox": (x, y, w, h), "conf": float,
              "class_id": int, "class_name": str}, ...]
        """
        # YOLOv5 需要 640x640 输入
        h, w = frame.shape[:2]
        resized = cv2.resize(frame, (640, 640))
        cv2.imwrite(self._tmp_input, resized)

        # 调用 NPU 推理
        try:
            result = subprocess.run(
                [YOLOV5_BIN, YOLOV5_MODEL, self._tmp_input],
                capture_output=True, text=True, timeout=5,
                cwd="/opt/yolov5",
                env={**os.environ, "LD_LIBRARY_PATH": YOLOV5_LIB},
            )
        except subprocess.TimeoutExpired:
            return []

        # 解析输出（检测结果在 stderr）
        detections = []
        for line in result.stderr.split("\n"):
            line = line.strip()
            # 格式: "16:  82%, [ 112,  233,  257,  609], dog"
            if ":" in line and "%," in line and "[" in line:
                try:
                    parts = line.split(",")
                    # 类别 ID
                    cls_id = int(parts[0].split(":")[0].strip())
                    # 置信度
                    conf_str = parts[0].split(":")[1].strip().replace("%", "")
                    conf = float(conf_str) / 100.0

                    if conf < self.conf:
                        continue

                    # 边界框 [x1, y1, x2, y2]
                    bbox_str = line.split("[")[1].split("]")[0]
                    coords = [int(x.strip()) for x in bbox_str.split(",")]
                    x1, y1, x2, y2 = coords

                    # 缩放回原始分辨率
                    sx = w / 640
                    sy = h / 640
                    bx = int(x1 * sx)
                    by = int(y1 * sy)
                    bw = int((x2 - x1) * sx)
                    bh = int((y2 - y1) * sy)
                    cx = bx + bw // 2
                    cy = by + bh // 2

                    cls_name = COCO_CLASSES[cls_id] if cls_id < len(COCO_CLASSES) else f"cls_{cls_id}"

                    detections.append({
                        "center": (cx, cy),
                        "bbox": (bx, by, bw, bh),
                        "conf": conf,
                        "class_id": cls_id,
                        "class_name": cls_name,
                    })
                except (ValueError, IndexError):
                    continue

        detections.sort(key=lambda d: d["conf"], reverse=True)
        return detections

    def draw(self, frame, detections, color=(0, 255, 0)):
        """在帧上绘制检测结果。"""
        for d in detections:
            bx, by, bw, bh = d["bbox"]
            cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), color, 2)
            label = f"{d['class_name']} {d['conf']:.0%}"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(frame, (bx, by - th - 6), (bx + tw, by), color, -1)
            cv2.putText(frame, label, (bx, by - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
            cv2.circle(frame, d["center"], 4, (0, 0, 255), -1)
        return frame
