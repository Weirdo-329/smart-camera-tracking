"""全局配置参数"""

# 摄像头参数
CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 720
FPS = 30

# 手部检测参数
HAND_DETECTION_CONFIDENCE = 0.7
HAND_TRACKING_CONFIDENCE = 0.5
MAX_NUM_HANDS = 2
MODEL_COMPLEXITY = 1  # 0=轻量, 1=标准

# 目标搜索区域（以手为中心的扩展像素）
SEARCH_REGION_PADDING = 150

# HSV 颜色范围定义（可配置多种颜色）
# 格式: {"颜色名": (lower_hsv, upper_hsv)}
COLOR_RANGES = {
    "red": ([0, 120, 70], [10, 255, 255]),       # 红色范围1
    "red2": ([170, 120, 70], [180, 255, 255]),    # 红色范围2（跨0度）
    "blue": ([100, 150, 50], [130, 255, 255]),    # 蓝色
    "green": ([35, 100, 50], [85, 255, 255]),     # 绿色
    "yellow": ([20, 100, 100], [35, 255, 255]),   # 黄色
}

# 形态学操作核大小
MORPH_KERNEL_SIZE = 5

# 轮廓面积过滤（像素²）
MIN_CONTOUR_AREA = 500
MAX_CONTOUR_AREA = 50000

# 画面中心坐标
FRAME_CENTER_X = CAMERA_WIDTH // 2   # 640
FRAME_CENTER_Y = CAMERA_HEIGHT // 2  # 360

# 舵机控制参数（PWM 直驱）
# 舵机1(pan 水平)：物理引脚7 → pwmchip20/pwm2
# 舵机2(tilt 垂直)：物理引脚29 → pwmchip0/pwm0

# 启动初始角度（根据实际安装方向调整）
# 摄像头正对前方时 pan/tilt 各是什么角度就填多少
PAN_INIT_ANGLE = 90
TILT_INIT_ANGLE = 120  # 如果启动时朝下，减小这个值（如 30~60）

# 角度限幅
PAN_MIN_ANGLE = 0
PAN_MAX_ANGLE = 180
# TILT_MIN_ANGLE = 90
# TILT_MAX_ANGLE = 120
TILT_MIN_ANGLE = 0
TILT_MAX_ANGLE = 180

# 偏移量死区（像素），小于该值不发送指令
DEADZONE_X = 30
DEADZONE_Y = 30

# 偏移量缩放系数（将像素偏移转换为舵机角度增量）
# 画面 640px 偏移 ≈ 舵机转 10°，可现场调整
OFFSET_SCALE_X = 0.02
OFFSET_SCALE_Y = 0.02

# 手动模式控制参数
MANUAL_STEP = 3.0        # 每次按键/点击的步进角度
# 方向符号（如果方向反了改成 -1）
MANUAL_PAN_SIGN = -1      # pan 舵机方向符号
MANUAL_TILT_SIGN = 1     # tilt 舵机方向符号
OFFSET_SCALE_Y = 0.02
