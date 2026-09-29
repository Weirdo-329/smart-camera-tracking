"""舵机测试脚本 — 让两个舵机来回摆动，验证接线是否正确"""

import time
import os

# 舵机 PWM 配置
SERVO1_CHIP = "pwmchip20"   # 物理引脚 7 (PL4, PWM0-2)
SERVO1_CHANNEL = "2"
SERVO2_CHIP = "pwmchip0"    # 物理引脚 29 (PD0)
SERVO2_CHANNEL = "0"

PERIOD = 20000000  # 20ms = 50Hz
DUTY_MIN = 500000    # 0.5ms = 0°
DUTY_MID = 1500000   # 1.5ms = 90°
DUTY_MAX = 2500000   # 2.5ms = 180°


def write_pwm(path, value):
    with open(path, "w") as f:
        f.write(str(value))


def setup_servo(chip, channel):
    base = f"/sys/class/pwm/{chip}"
    pwm_dir = f"{base}/pwm{channel}"

    # 导出（如果还没导出）
    if not os.path.exists(pwm_dir):
        try:
            write_pwm(f"{base}/export", channel)
            time.sleep(0.3)
        except PermissionError:
            print(f"!!! 无权限导出 {chip}/pwm{channel}")
            print("!!! 请用 sudo 运行: sudo python3 servo_test.py")
            return None

    # 设置周期
    write_pwm(f"{pwm_dir}/period", PERIOD)
    time.sleep(0.1)

    # 修正极性（关键！默认是 inversed，舵机不认）
    try:
        write_pwm(f"{pwm_dir}/polarity", "normal")
        time.sleep(0.1)
    except (PermissionError, IOError):
        print(f"!!! 无法修改极性，请确认用 sudo 运行")

    return pwm_dir


def set_servo(pwm_dir, duty):
    """设置舵机角度（duty 单位纳秒）"""
    write_pwm(f"{pwm_dir}/duty_cycle", duty)
    write_pwm(f"{pwm_dir}/enable", 1)


def swing(pwm_dir, name):
    """让舵机 0°→180°→90° 摆动"""
    print(f"{name}: 转到 0°")
    set_servo(pwm_dir, DUTY_MIN)
    time.sleep(1.5)
    print(f"{name}: 转到 180°")
    set_servo(pwm_dir, DUTY_MAX)
    time.sleep(1.5)
    print(f"{name}: 回到 90°")
    set_servo(pwm_dir, DUTY_MID)
    time.sleep(1.5)


def main():
    print("=" * 40)
    print("DS3115 舵机测试")
    print("=" * 40)

    # 舵机1：物理引脚 7
    pwm1 = setup_servo(SERVO1_CHIP, SERVO1_CHANNEL)
    # 舵机2：物理引脚 29
    pwm2 = setup_servo(SERVO2_CHIP, SERVO2_CHANNEL)

    if pwm1 is None and pwm2 is None:
        print("\n请先以 sudo 运行: sudo python3 servo_test.py")
        return

    if pwm1:
        print(f"\n舵机1（物理引脚7）开始摆动...")
        print("如果舵机不动，请检查:")
        print("  1. 舵机红线接外部5V电源正极")
        print("  2. 舵机黑线接外部电源负极，且必须与香橙派GND相连")
        print("  3. 舵机信号线（白/黄）接物理引脚7")
        swing(pwm1, "舵机1")

    if pwm2:
        print(f"\n舵机2（物理引脚29）开始摆动...")
        swing(pwm2, "舵机2")

    print("\n测试完成")
    print("注意：DS3115 工作电压 4.8-6V，堵转电流 1.5-2.5A")
    print("两个舵机必须用外部电源供电，不能直接用香橙派5V引脚!")


if __name__ == "__main__":
    main()
