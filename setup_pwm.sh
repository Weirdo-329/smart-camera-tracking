#!/bin/bash
# 一次性初始化 PWM 通道权限（用 sudo 运行一次即可）
# 之后普通用户就能直接控制舵机
# 初始角度从 config.py 读取

set -e

echo "初始化 PWM 通道..."

# 从 config.py 读取初始角度
CFG_FILE="$(dirname "$0")/config.py"
if [ -f "$CFG_FILE" ]; then
    PAN_INIT=$(grep -oP 'PAN_INIT_ANGLE\s*=\s*\K\d+' "$CFG_FILE" | head -1)
    TILT_INIT=$(grep -oP 'TILT_INIT_ANGLE\s*=\s*\K\d+' "$CFG_FILE" | head -1)
else
    PAN_INIT=90
    TILT_INIT=90
fi
PAN_INIT=${PAN_INIT:-90}
TILT_INIT=${TILT_INIT:-90}
echo "  初始角度: pan=$PAN_INIT° tilt=$TILT_INIT°"

# 角度 → 占空比（纳秒）
# duty = 500000 + angle/180 * 2000000
angle_to_duty() {
    echo $((500000 + $1 * 2000000 / 180))
}

PAN_DUTY=$(angle_to_duty $PAN_INIT)
TILT_DUTY=$(angle_to_duty $TILT_INIT)

# 舵机1: pwmchip20/pwm2 (物理引脚7)
# 舵机2: pwmchip0/pwm0  (物理引脚29)

setup_channel() {
    local chip=$1
    local ch=$2
    local duty=$3
    local base="/sys/class/pwm/$chip"

    echo "  $chip/pwm$ch (duty=$duty ns) ..."

    # 导出
    if [ ! -d "$base/pwm$ch" ]; then
        echo "$ch" > "$base/export"
        sleep 0.2
    fi

    # 设置周期 20ms
    echo 20000000 > "$base/pwm$ch/period"
    sleep 0.1

    # 修正极性
    echo normal > "$base/pwm$ch/polarity"
    sleep 0.1

    # 设置初始角度
    echo "$duty" > "$base/pwm$ch/duty_cycle"
    echo 1 > "$base/pwm$ch/enable"

    # 开放权限给普通用户
    chmod 666 "$base/pwm$ch"/*
    echo "    完成"
}

setup_channel pwmchip20 2 "$PAN_DUTY"
setup_channel pwmchip0 0 "$TILT_DUTY"

# 开放导出接口权限
chmod 666 /sys/class/pwm/pwmchip20/export /sys/class/pwm/pwmchip20/unexport
chmod 666 /sys/class/pwm/pwmchip0/export /sys/class/pwm/pwmchip0/unexport

echo ""
echo "初始化完成！舵机已转到初始角度 (pan=$PAN_INIT° tilt=$TILT_INIT°)"
echo "现在可以直接运行: DISPLAY=:0 python3 -u main.py"
