#!/bin/sh
# Launcher Xiaozhi AI (hybrid) cho TrimUI Brick Pro — Stock OS.
# Chạy từ menu Apps: MainUI thoát trước khi gọi launch.sh; runtrimui tự chạy lại MainUI khi app thoát.
APPDIR=/mnt/SDCARD/Apps/XiaozhiAI
LOG=/tmp/xiaozhi_app.log

. /mnt/SDCARD/System/etc/ex_config 2>/dev/null
export PYTHONPATH="$APPDIR/pylibs"
# MainUI chạy app KHÔNG có HOME → py-xiaozhi đọc /.local/... (cấu hình trống, chưa kích hoạt)
# → URL websocket = None → lỗi server. Cấu hình đã kích hoạt nằm ở /root/.local/share/py-xiaozhi.
export HOME=/root
# Âm thanh ra (đo 2026-10-08):
# - 'default' báo 128ch → upmix 1ch→128ch real-time → TREO CỨNG MÁY.
# - 'default' + 2ch → PortAudio đứng sau 3 callback → CÂM.
# - PlaybackDmix 48000Hz 2ch: đủ nhịp, không underflow (cùng đường với aplay). 48000 = 2×24000 TTS.
export XIAOZHI_OUTPUT_CHANNELS=2
export XIAOZHI_OUTPUT_DEVICE=PlaybackDmix
export XIAOZHI_OUTPUT_RATE=48000
# Khuếch đại phần mềm TTS: 4 làm RÈ (TTS server đã gần đỉnh) → giữ 1.
export XIAOZHI_OUTPUT_GAIN=1
# Bỏ công cụ MCP vô dụng trên máy cầm tay (camera → openai, chụp màn hình, app desktop,
# âm lượng 'Master'). Xem nguon/patch_lite.py.
export XIAOZHI_TRIMUI_LITE=1
cd "$APPDIR" || exit 1

# Chắc chắn MainUI/keymon đã nhả codec + không ghi đè mixer trong lúc app chạy.
killall -9 MainUI 2>/dev/null
killall -9 keymon 2>/dev/null
sleep 1

# Bật công tắc + mạch loa, mic gain. KHÔNG đổi mức âm lượng (giữ mức MainUI để lại:
# Headphone Volume=1, digital=0, DAC=140 — 2 control đầu có thang NGƯỢC so với chú thích dB).
sh "$APPDIR/set_loa_max.sh" 2>/dev/null

echo "===== Xiaozhi khoi dong $(date) =====" >> "$LOG"
python3 trimui_run.py >> "$LOG" 2>&1

# App thoát (nút MENU). Vòng lặp runtrimui của hệ thống sẽ tự chạy lại MainUI + keymon.
echo "===== Xiaozhi thoat $(date) =====" >> "$LOG"
exit 0
