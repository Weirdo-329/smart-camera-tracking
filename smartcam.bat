@echo off
title Smart Camera Stream

echo ========================================
echo   Smart Camera Tracking System - Viewer
echo ========================================
echo.
echo Checking Orange Pi connection...
ping -n 1 -w 1000 orangepi4pro.local >nul 2>&1
if %errorlevel%==0 (
    echo Orange Pi is online. Opening stream...
    start http://orangepi4pro.local:8080
    echo Browser opened!
    timeout /t 3 >nul
    exit
)

echo.
echo Cannot connect to Orange Pi. Possible reasons:
echo   1. Orange Pi is not powered on, or main.py is not running
echo   2. avahi service is not installed on Orange Pi
echo      (Run: sudo apt install avahi-daemon)
echo   3. PC and Orange Pi are not on the same WiFi
echo.
echo Tip: Run "hostname -I" on Orange Pi to get its IP,
echo then open http://IP:8080 in your browser manually.
echo.
pause
