"""全局配置参数"""

# ========== 摄像头参数 ==========
# 采集分辨率（与处理分辨率一致时性能最佳；如需推流全高清可改为 1920x1080，
# 但会因 1080p 解码/编码开销损失约 1/3 帧率）
CAMERA_CAPTURE_WIDTH = 1280
CAMERA_CAPTURE_HEIGHT = 720
# 处理分辨率（检测/跟踪/控制用）
CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 720
FPS = 30

# ========== 目标检测参数 ==========
# 是否启用 NPU 自动检测（True=手动模式显示检测框可点击锁定；
# False=纯手动拖框选择目标）
AUTO_DETECT_ENABLE = True
# 检测间隔（每 N 帧运行一次 NPU 检测）
DETECT_INTERVAL = 10
# 检测置信度阈值
DETECT_CONFIDENCE = 0.4

# 画面中心坐标（处理分辨率）
FRAME_CENTER_X = CAMERA_WIDTH // 2   # 640
FRAME_CENTER_Y = CAMERA_HEIGHT // 2  # 360

# ========== 舵机控制参数（PWM 直驱） ==========
# 舵机1(pan 水平)：物理引脚7 → pwmchip20/pwm2
# 舵机2(tilt 垂直)：物理引脚29 → pwmchip0/pwm0

# 启动初始角度（根据实际安装方向调整）
PAN_INIT_ANGLE = 90
TILT_INIT_ANGLE = 150

# 角度限幅
PAN_MIN_ANGLE = 0
PAN_MAX_ANGLE = 180
TILT_MIN_ANGLE = 0
TILT_MAX_ANGLE = 180

# 偏移量死区（像素），小于该值不发送指令
DEADZONE_X = 30
DEADZONE_Y = 30

# ========== 手动模式控制参数 ==========
MANUAL_STEP = 3.0        # 每次按键/点击的步进角度
# 方向符号（如果方向反了改成 -1）
MANUAL_PAN_SIGN = -1     # pan 舵机方向符号
MANUAL_TILT_SIGN = 1     # tilt 舵机方向符号
