#!/bin/sh
# Bật đường ra loa TrimUI Brick Pro — KHÔNG đụng vào mức âm lượng.
# ĐÍNH CHÍNH (đo 2026-10-08): mức âm lượng ĐÚNG là mức MainUI để lại (menu phát to):
#   'Headphone Volume' = 1, 'digital volume' = 0, 'DAC volume' = 140,140.
# Thang của 2 control 'Headphone Volume' (0-7) và 'digital volume' (0-63) bị NGƯỢC
# so với chú thích dB của driver: số nhỏ = to. Đặt 7/63 làm loa bé hoặc câm.
# Vì vậy script chỉ bật công tắc/mạch loa, giữ nguyên âm lượng hệ thống (phím vol vẫn dùng được).
C="amixer -D hw:audiocodec"
echo 0 > /sys/class/speaker/mute 2>/dev/null          # bật mạch khuếch đại loa (gpio SPK)
$C sset 'Headphone Switch' on        >/dev/null 2>&1   # bật đường tai nghe/loa
$C sset 'HpSpeaker Switch' on        >/dev/null 2>&1   # bật loa ngoài
# Mic gain cho thu âm (chế độ server)
$C sset 'ADCL Input MIC1 Boost Switch' on >/dev/null 2>&1
$C sset 'ADCR Input MIC2 Boost Switch' on >/dev/null 2>&1
$C cset name='MIC1 gain volume' 24   >/dev/null 2>&1
$C cset name='MIC2 gain volume' 24   >/dev/null 2>&1
