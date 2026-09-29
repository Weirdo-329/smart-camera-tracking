#!/bin/bash
# 智能摄像头系统启动脚本（双击桌面图标运行）
export DISPLAY=:0
cd /home/orangepi/Desktop/Graduation_project
exec python3 -u main.py
