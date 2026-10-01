"""智能摄像头 — YOLO 检测 + 框选锁定 + 跟踪主程序"""

import cv2
import time
import threading
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """多线程 HTTP 服务器，避免单连接阻塞整个服务"""
    daemon_threads = True
import config
from smart_tracker import SmartTracker, _draw_chinese
from servo_controller import ServoController
from touch_handler import ZoomController


# 全局变量：最新帧（用于 HTTP 推流）
_latest_frame = None
_frame_lock = threading.Lock()


class StreamHandler(BaseHTTPRequestHandler):
    """MJPEG 推流 HTTP 处理器"""

    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            html = """<html><head><title>Smart Camera</title>
            <style>
            body{margin:0;background:#000;overflow:hidden}
            img{width:100vw;height:100vh;object-fit:contain}
            </style></head>
            <body><img src="/stream"></body></html>"""
            self.wfile.write(html.encode())

        elif self.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            try:
                while True:
                    with _frame_lock:
                        if _latest_frame is None:
                            time.sleep(0.01)
                            continue
                        _, buf = cv2.imencode(".jpg", _latest_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n\r\n")
                    self.wfile.write(buf.tobytes())
                    self.wfile.write(b"\r\n")
                    time.sleep(1.0 / config.FPS)
            except (BrokenPipeError, ConnectionResetError):
                pass

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def start_stream_server(port=8080):
    # ThreadingHTTPServer：每个连接独立线程，退出时不会被卡住
    server = ThreadingHTTPServer(("0.0.0.0", port), StreamHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def main():
    parser = argparse.ArgumentParser(description="智能摄像头 - 框选锁定跟踪")
    parser.add_argument("--no-display", action="store_true", help="不在本地屏幕显示")
    parser.add_argument("--no-stream", action="store_true", help="不启用 HTTP 推流")
    parser.add_argument("--port", type=int, default=8080, help="推流端口（默认 8080）")
    parser.add_argument("--save", type=str, default=None, help="保存录像到文件")
    args = parser.parse_args()

    use_display = not args.no_display
    use_stream = not args.no_stream

    print("=" * 50)
    print("智能摄像头 - 框选锁定跟踪系统")
    print("=" * 50)
    print(f"采集: {config.CAMERA_CAPTURE_WIDTH}x{config.CAMERA_CAPTURE_HEIGHT} @ {config.FPS}fps")
    print(f"处理: {config.CAMERA_WIDTH}x{config.CAMERA_HEIGHT}（推流保持采集分辨率）")

    # 初始化摄像头（按采集分辨率打开）
    cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.CAMERA_CAPTURE_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAMERA_CAPTURE_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, config.FPS)

    if not cap.isOpened():
        print("[ERROR] 无法打开摄像头")
        return

    # 初始化跟踪器和舵机
    servo = ServoController()
    tracker = SmartTracker()
    # 绑定手动模式回调：方向按钮 → 舵机步进
    tracker.manual_move_callback = servo.step_move

    # 缩放控制
    zoom = ZoomController("/dev/input/event6")
    # 绑定屏幕缩放按钮回调
    tracker.zoom_callback = lambda name: zoom.handle_key(ord("+") if name == "in" else ord("-"))
    # 绑定屏幕退出按钮回调（等效按 q）
    exit_flag = {"value": False}
    tracker.exit_callback = lambda: exit_flag.update({"value": True})

    # 启动推流
    server = None
    if use_stream:
        server = start_stream_server(args.port)
        import socket
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        print(f"推流地址: http://{local_ip}:{args.port}")

    # 录像
    writer = None
    if args.save:
        fourcc = cv2.VideoWriter_fourcc(*"XVID")
        writer = cv2.VideoWriter(args.save, fourcc, config.FPS, (config.CAMERA_WIDTH, config.CAMERA_HEIGHT))
        print(f"录像保存到: {args.save}")

    print("=" * 50)
    print("操作说明：")
    print("  【手动模式】拖拽画框 → 锁定目标进入自动跟踪")
    print("  【手动模式】WASD/方向键/屏幕方向按钮 → 控制云台")
    print("  【自动模式】点'取消跟踪'按钮或点空白处 → 切回手动")
    print("  +/- 键        → 缩放画面")
    print("  0 键          → 重置缩放")
    print("  q 键          → 退出")
    print("=" * 50)

    # 窗口设置：自动适配屏幕大小（留出标题栏和任务栏空间）
    import subprocess
    import re as _re
    screen_w, screen_h = 1024, 600
    try:
        out = subprocess.check_output(["xrandr", "--current"], text=True, timeout=3)
        m = _re.search(r"current (\d+) x (\d+)", out)
        if m:
            screen_w, screen_h = int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    print(f"屏幕分辨率: {screen_w}x{screen_h}")
    display_w = screen_w - 40      # 左右留边
    display_h = screen_h - 90      # 上下留边（标题栏+任务栏）
    window_created = False

    # FPS
    fps_timer = time.time()
    frame_count = 0
    fps_display = 0.0

    global _latest_frame

    # 推流/采集分辨率与处理分辨率的比例
    stream_scale = config.CAMERA_CAPTURE_WIDTH / config.CAMERA_WIDTH

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("[WARN] 读取帧失败")
                continue

            # 缩小到处理分辨率做检测/跟踪（720p）
            proc_frame = cv2.resize(frame, (config.CAMERA_WIDTH, config.CAMERA_HEIGHT))
            result = tracker.update(proc_frame)

            # 发送偏移量给舵机
            if result.has_target:
                servo.send_offset(result.offset_dx, result.offset_dy)

            # 计算 FPS
            frame_count += 1
            elapsed = time.time() - fps_timer
            if elapsed >= 1.0:
                fps_display = frame_count / elapsed
                frame_count = 0
                fps_timer = time.time()

            # 绘制内容层（目标框/箭头/十字，随缩放移动）
            annotated = proc_frame.copy()
            annotated = tracker.draw(annotated, result)

            # 应用缩放（只作用于画面内容）
            if zoom.zoom_level > 1.0:
                annotated = zoom.apply_zoom(annotated)

            # 绘制 UI 层（按钮/状态文字，固定在屏幕）
            annotated = tracker.draw_ui(annotated, result)

            cv2.putText(
                annotated, f"FPS: {fps_display:.1f}",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2,
            )

            if result.tracking_state == "tracking":
                status = "[自动模式] 跟踪中: 点'取消跟踪'或点空白处切回手动"
            else:
                status = "[手动模式] 拖拽画框锁定目标 | WASD/方向键/屏幕按钮 控制云台"
            _draw_chinese(annotated, status, (12, 60), 22, (0, 255, 255), anchor="left")

            if zoom.zoom_level > 1.0:
                cv2.putText(
                    annotated, f"Zoom: {zoom.zoom_level:.1f}x",
                    (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2,
                )

            # 推流（只推干净画面，缩放跟随本地显示）
            if use_stream:
                if zoom.zoom_level > 1.0:
                    # 缩放中心从 720p 处理坐标换算到采集分辨率坐标
                    saved_center = zoom.zoom_center
                    if saved_center:
                        zoom.zoom_center = (int(saved_center[0] * stream_scale),
                                            int(saved_center[1] * stream_scale))
                    stream_frame = zoom.apply_zoom(frame.copy())
                    zoom.zoom_center = saved_center
                else:
                    stream_frame = frame.copy()
                with _frame_lock:
                    _latest_frame = stream_frame

            # 录像
            if writer:
                writer.write(annotated)

            # 本地显示（720p 处理画面）
            if use_display:
                if not window_created:
                    cv2.namedWindow("Smart Camera", cv2.WINDOW_NORMAL)
                    cv2.setWindowProperty("Smart Camera", cv2.WND_PROP_FULLSCREEN,
                                          cv2.WINDOW_FULLSCREEN)
                    cv2.resizeWindow("Smart Camera", display_w, display_h)

                    # OpenCV 会自动把窗口鼠标坐标换算到画面坐标，直接使用
                    cv2.setMouseCallback("Smart Camera", tracker.handle_mouse)
                    window_created = True
                    zoom.start_touch()

                cv2.imshow("Smart Camera", annotated)
                key = cv2.waitKeyEx(1) & 0xFFFF

                if key == ord("q") or exit_flag["value"]:
                    break

                # 数字键选择目标
                if ord("1") <= key <= ord("9"):
                    tracker.select_by_index(key - ord("1"))

                # 手动模式：WASD / 方向键控制云台
                if tracker.mode == "manual":
                    dir_map = {
                        ord("w"): "up", ord("W"): "up",
                        ord("s"): "down", ord("S"): "down",
                        ord("a"): "left", ord("A"): "left",
                        ord("d"): "right", ord("D"): "right",
                        65362: "up",      # 方向键↑
                        65364: "down",    # 方向键↓
                        65361: "left",    # 方向键←
                        65363: "right",   # 方向键→
                    }
                    if key in dir_map:
                        servo.step_move(dir_map[key])

                # 缩放
                zoom.handle_key(key)

    except KeyboardInterrupt:
        print("\n用户中断")
    finally:
        zoom.stop()
        cap.release()
        tracker.release()
        servo.release()
        if writer:
            writer.release()
        if use_display:
            cv2.destroyAllWindows()
        # 推流线程是 daemon，随进程结束自动清理，不调用阻塞的 shutdown()
        print("程序已退出")


if __name__ == "__main__":
    main()
