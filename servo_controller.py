"""舵机控制模块 — 通过 PWM 控制云台两个 DS3115 舵机（PID 控制）"""

import os
import time
import config


class PID:
    """增量式 PID 控制器"""

    def __init__(self, kp, ki, kd, output_limit=1.0, integral_limit=50.0):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.output_limit = output_limit
        self.integral_limit = integral_limit

        self.prev_error = 0.0
        self.integral = 0.0

    def reset(self):
        self.prev_error = 0.0
        self.integral = 0.0

    def decay_integral(self, factor=0.8):
        """积分缓衰减（死区内用，保留微分记忆不丢阻尼）。"""
        self.integral *= factor

    def update(self, error, dt=1.0):
        """
        计算 PID 输出。

        参数:
            error: 当前误差（像素偏移）
            dt: 时间间隔（帧数，简化处理）
        """
        # 比例项
        p = self.kp * error

        # 积分项（带限幅防积分饱和）
        self.integral += error * dt
        self.integral = max(-self.integral_limit, min(self.integral_limit, self.integral))
        i = self.ki * self.integral

        # 微分项（阻尼振荡的关键）
        d = self.kd * (error - self.prev_error) / dt
        self.prev_error = error

        output = p + i + d
        output = max(-self.output_limit, min(self.output_limit, output))
        return output


class ServoController:
    def __init__(self):
        # 舵机 PWM 配置
        # 舵机1 = 水平(pan)：物理引脚 7 (PL4) → pwmchip20/pwm2
        # 舵机2 = 垂直(tilt)：物理引脚 29 (PD0) → pwmchip0/pwm0
        self.servos = {
            "pan": {
                "chip": "pwmchip20",
                "channel": "2",
                "angle": config.PAN_INIT_ANGLE,   # 初始角度
                "min_angle": config.PAN_MIN_ANGLE,
                "max_angle": config.PAN_MAX_ANGLE,
            },
            "tilt": {
                "chip": "pwmchip0",
                "channel": "0",
                "angle": config.TILT_INIT_ANGLE,  # 初始角度
                "min_angle": config.TILT_MIN_ANGLE,
                "max_angle": config.TILT_MAX_ANGLE,
            },
        }

        # PID 控制器（pan 和 tilt 各一个）
        # 参数说明：
        #   kp: 比例 — 误差大转得快
        #   ki: 积分 — 消除稳态误差（目标永远差一点）
        #   kd: 微分 — 阻尼振荡（摇晃就加大它）
        self.pid_pan = PID(kp=0.004, ki=0.005, kd=0.05, output_limit=1.5)
        self.pid_tilt = PID(kp=0.005, ki=0.002, kd=0.05, output_limit=1.5)

        self.period = 20000000        # 20ms = 50Hz（舵机标准频率）
        self.duty_min = 500000        # 0.5ms → 0°
        self.duty_mid = 1500000       # 1.5ms → 90°
        self.duty_max = 2500000       # 2.5ms → 180°

        # 偏移量低通滤波（平滑 KCF 位置抖动，让舵机运动更柔和）
        self._smooth_dx = 0.0
        self._smooth_dy = 0.0
        self._smooth_alpha = 0.25     # 0~1，越小越平滑（响应也越慢）

        # 死区迟滞状态（防止目标在死区边界来回振荡）
        self._in_deadzone = False

        self.enabled = True
        self._setup()

    def _setup(self):
        """初始化 PWM 通道。"""
        for name, servo in self.servos.items():
            base = f"/sys/class/pwm/{servo['chip']}"
            pwm_dir = f"{base}/pwm{servo['channel']}"

            try:
                # 导出通道
                if not os.path.exists(pwm_dir):
                    with open(f"{base}/export", "w") as f:
                        f.write(servo["channel"])
                    time.sleep(0.2)

                # 周期（必须先于 duty 设置）
                with open(f"{pwm_dir}/period", "w") as f:
                    f.write(str(self.period))
                time.sleep(0.1)

                # 极性修正（默认 inversed，必须改 normal）
                with open(f"{pwm_dir}/polarity", "w") as f:
                    f.write("normal")
                time.sleep(0.1)

                servo["pwm_dir"] = pwm_dir
                print(f"[ServoController] {name} PWM 初始化成功 ({pwm_dir})")

                # 转到初始角度
                self.set_angle(name, servo["angle"])
            except PermissionError:
                print(f"[ServoController] 无权限操作 {pwm_dir}")
                print("[ServoController] 请用 sudo 运行，或执行:")
                print(f"  sudo chmod 666 {base}/export {base}/unexport")
                print(f"  sudo chmod 666 {pwm_dir}/*")
                servo["pwm_dir"] = None
                self.enabled = False
            except FileNotFoundError:
                print(f"[ServoController] PWM 通道不存在: {pwm_dir}")
                print("[ServoController] 请确认 /boot/orangepiEnv.txt 中 overlays 包含 pwm0 spwm2")
                servo["pwm_dir"] = None
                self.enabled = False

    def _set_duty(self, name, duty_ns):
        """设置 PWM 占空比（纳秒）。"""
        servo = self.servos[name]
        if servo.get("pwm_dir") is None:
            return
        with open(f"{servo['pwm_dir']}/duty_cycle", "w") as f:
            f.write(str(int(duty_ns)))
        with open(f"{servo['pwm_dir']}/enable", "w") as f:
            f.write("1")

    def set_angle(self, name, angle):
        """设置舵机角度（0-180）。"""
        if not self.enabled:
            return
        servo = self.servos[name]
        angle = max(servo["min_angle"], min(servo["max_angle"], angle))
        # 角度 → 占空比（线性映射）
        duty = self.duty_min + (angle / 180.0) * (self.duty_max - self.duty_min)
        self._set_duty(name, duty)
        servo["angle"] = angle

    def get_angle(self, name):
        """获取当前角度。"""
        return self.servos[name]["angle"]

    def send_offset(self, dx, dy):
        """
        根据画面偏移量调整云台角度（PID 控制）。

        参数:
            dx: 水平偏移（正值=目标在右）
            dy: 垂直偏移（正值=目标在下）
        """
        if not self.enabled:
            # 无 PWM 权限时打印调试信息
            print(f"[Servo] dx:{dx} dy:{dy}")
            return

        # 低通滤波平滑偏移量（滤掉 KCF 抖动）
        self._smooth_dx = self._smooth_alpha * dx + (1 - self._smooth_alpha) * self._smooth_dx
        self._smooth_dy = self._smooth_alpha * dy + (1 - self._smooth_alpha) * self._smooth_dy
        sx, sy = self._smooth_dx, self._smooth_dy

        # 死区判断（带迟滞：进入死区阈值 DEADZONE，退出需要 1.6 倍，
        # 防止目标在边界附近来回跨线触发振荡）
        if self._in_deadzone:
            exit_th = 1.6
        else:
            exit_th = 1.0

        if abs(sx) < config.DEADZONE_X * exit_th and abs(sy) < config.DEADZONE_Y * exit_th:
            self._in_deadzone = True
            # 积分缓衰减（不 reset：保留微分记忆，振荡时才能刹车）
            self.pid_pan.decay_integral(0.8)
            self.pid_tilt.decay_integral(0.8)
            return

        self._in_deadzone = False

        # PID 计算角度增量（负号：目标偏右云台向右转，方向现场可调）
        delta_pan = -self.pid_pan.update(sx)
        delta_tilt = self.pid_tilt.update(sy)

        new_pan = self.servos["pan"]["angle"] + delta_pan
        new_tilt = self.servos["tilt"]["angle"] + delta_tilt

        # 限幅
        new_pan = max(self.servos["pan"]["min_angle"], min(self.servos["pan"]["max_angle"], new_pan))
        new_tilt = max(self.servos["tilt"]["min_angle"], min(self.servos["tilt"]["max_angle"], new_tilt))

        self.set_angle("pan", new_pan)
        self.set_angle("tilt", new_tilt)

    def step_move(self, direction, step=None):
        """
        手动模式步进控制。

        参数:
            direction: "up" / "down" / "left" / "right"
            step: 每次步进的角度（默认取 config.MANUAL_STEP）
        """
        if not self.enabled:
            return
        step = step if step is not None else config.MANUAL_STEP

        # 方向 → 舵机 + 角度增量（符号可根据安装方向在 config 调整）
        if direction == "left":
            name, delta = "pan", -config.MANUAL_PAN_SIGN * step
        elif direction == "right":
            name, delta = "pan", config.MANUAL_PAN_SIGN * step
        elif direction == "up":
            name, delta = "tilt", -config.MANUAL_TILT_SIGN * step
        elif direction == "down":
            name, delta = "tilt", config.MANUAL_TILT_SIGN * step
        else:
            return

        # 手动操作时重置 PID 和平滑滤波，防止切回自动时积分突跳
        self.pid_pan.reset()
        self.pid_tilt.reset()
        self._smooth_dx = 0.0
        self._smooth_dy = 0.0

        new_angle = self.servos[name]["angle"] + delta
        self.set_angle(name, new_angle)

    def reset(self):
        """云台回到初始角度。"""
        self.pid_pan.reset()
        self.pid_tilt.reset()
        self._smooth_dx = 0.0
        self._smooth_dy = 0.0
        self.set_angle("pan", config.PAN_INIT_ANGLE)
        self.set_angle("tilt", config.TILT_INIT_ANGLE)

    def release(self):
        """关闭 PWM。"""
        for name, servo in self.servos.items():
            if servo.get("pwm_dir"):
                try:
                    with open(f"{servo['pwm_dir']}/enable", "w") as f:
                        f.write("0")
                    print(f"[ServoController] {name} PWM 已关闭")
                except (PermissionError, IOError):
                    pass
