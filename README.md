# 智能摄像头自动跟踪系统

> 基于香橙派 4 Pro 的二维云台自动跟拍系统 — 毕业设计项目

面向教学演示场景：摄像头自动跟踪教师手部操作区域，云台实时对准目标，画面同步推送至 PC 端供远程观摩。

## 功能特性

- **YOLOv5 目标检测**：部署于板载 NPU 加速推理（约 0.24s/帧）
- **手动框选锁定**：触摸屏拖拽画框指定任意跟踪目标
- **KCF 连续跟踪**：帧间轻量跟踪，640×360 缩小图上运行保证实时性
- **双轴 PID 控制**：P/I/D 三参数 + 死区 + 积分抗饱和 + 低通滤波平滑
- **手动/自动双模式**：方向按钮 / WASD / 方向键控制云台；框选后自动跟踪
- **1080p 分流方案**：采集 1920×1080 推流，处理缩至 1280×720 保证流畅
- **HTTP MJPEG 局域网推流**：PC 浏览器直接观看，mDNS 域名访问
- **屏幕交互 UI**：中文按钮（取消跟踪 / 方向 / 缩放 / 退出），PIL 渲染

## 硬件组成

| 组件 | 型号 |
|------|------|
| 主控 | 香橙派 4 Pro（T527，板载 NPU） |
| 摄像头 | USB 摄像头（1080p@30fps，MJPG） |
| 云台 | DS3115 数字舵机 ×2（pan / tilt） |
| 显示 | 7 寸电容触摸屏 1024×600 |
| 供电 | 香橙派 + 舵机外部 5V/5A（**必须共地**） |

**接线对照：**

| 信号 | 引脚 |
|------|------|
| pan 舵机信号 | 物理引脚 7（pwmchip20/pwm2） |
| tilt 舵机信号 | 物理引脚 29（pwmchip0/pwm0） |

## 软件架构

```
USB摄像头(1080p) ─┬─→ 缩小720p ─→ KCF跟踪 + PID控制 ─→ PWM ─→ 云台舵机
                  └─→ 原始1080p ─→ HTTP MJPEG推流 ─→ PC浏览器
```

```
main.py                    # 主程序（采集/显示/推流/键盘交互）
├── smart_tracker.py       # 框选锁定 + KCF 跟踪 + 屏幕 UI
├── npu_detector.py        # NPU YOLOv5 检测（调用 /opt/yolov5 二进制）
├── servo_controller.py    # PWM 舵机 + 双轴 PID + 低通滤波
├── touch_handler.py       # 缩放控制（键盘 + 屏幕按钮）
└── config.py              # 全局参数
```

## 环境准备

### 1. 依赖安装

```bash
pip3 install -r requirements.txt
```

### 2. 启用 PWM（修改 /boot/orangepiEnv.txt）

```
overlays=uart7 pwm0 spwm2
```

重启后执行：

```bash
sudo bash setup_pwm.sh          # 初始化 PWM 通道 + 开放权限
sudo cp pwm-init.service /etc/systemd/system/   # 开机自动初始化（可选）
sudo systemctl enable --now pwm-init.service
```

### 3. NPU 模型部署

板载 NPU 的 YOLOv5 二进制与模型位于 `/opt/yolov5/`（系统镜像自带）：

```
/opt/yolov5/yolov5          # NPU 推理二进制
/opt/yolov5/model/yolov5.nb # 转换后的模型
```

### 4. mDNS（PC 域名访问，可选）

```bash
sudo apt install avahi-daemon
sudo systemctl enable --now avahi-daemon
```

## 运行

```bash
# 本地屏幕 + 推流（默认）
DISPLAY=:0 python3 -u main.py

# 只推流 / 只显示
python3 -u main.py --no-display
python3 -u main.py --no-stream
```

PC 端浏览器打开 `http://orangepi4pro.local:8080`（或双击 `smartcam.bat`）。

## 操作说明

| 模式 | 操作 |
|------|------|
| 手动 | 屏幕方向按钮 / WASD / 方向键 控制云台 |
| 锁定 | 画面拖拽画框 → 进入自动跟踪 |
| 缩放 | 屏幕放大/缩小按钮 / `+` `-` 键，`0` 重置 |
| 取消跟踪 | 右上角按钮 / 点空白处 / 右键 |
| 退出 | 左上角红色退出按钮 / `q` 键 |

## 关键参数

```python
# config.py — 死区（像素）、手动步进、初始角度、限幅
DEADZONE_X = 30
MANUAL_STEP = 3.0
PAN_INIT_ANGLE = 90
TILT_INIT_ANGLE = 120

# servo_controller.py — PID（摇晃加大 kd，响应慢加大 kp）
PID(kp=0.004, ki=0.005, kd=0.03, output_limit=1.5)  # pan
PID(kp=0.005, ki=0.002, kd=0.03, output_limit=1.5)  # tilt
```

## 踩坑记录

1. **PWM 极性默认反相**（inversed），舵机不响应 → sysfs 改为 normal
2. **舵机供电**：两个 DS3115 堵转峰值 5A，必须外部电源 + 共地
3. **opencv-python 与 opencv-contrib-python 冲突**：后者被覆盖导致 Tracker 模块丢失
4. **HTTPServer 单线程阻塞**：PC 浏览器保持连接时退出卡死 → 换 ThreadingHTTPServer
5. **KCF 遮挡漂移**：目标被遮挡时跟踪框漂移导致云台失控（见下文）

## 已知限制

- KCF 目标被长时间遮挡时会漂移，未实现稳健的遮挡检测（曾尝试 YOLO 校验方案，因检测不稳定回退）
- NPU YOLOv5 为 COCO 预训练模型，对特定仪器（示波器等）识别有限，主要靠手动框选

## 项目结构

```
.
├── main.py                # 主程序入口
├── smart_tracker.py       # 跟踪器 + UI
├── npu_detector.py        # NPU 检测
├── servo_controller.py    # 舵机 + PID
├── touch_handler.py       # 缩放控制
├── config.py              # 配置
├── requirements.txt       # Python 依赖
├── setup_pwm.sh           # PWM 初始化脚本
├── servo_test.py          # 舵机测试工具
├── start_smartcam.sh      # 桌面启动脚本
├── smartcam.service       # systemd 服务（交付用）
├── pwm-init.service       # PWM 开机初始化服务
├── smartcam.bat           # PC 端推流查看器
└── 使用说明书.md           # 操作指导手册
```

## License

MIT
