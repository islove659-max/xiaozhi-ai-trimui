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

# MainUI phải nhả codec âm thanh. GIỮ keymon (2026-10-08): keymon lo phím âm lượng/độ sáng —
# tắt nó làm phím âm lượng chết. runtrimui chỉ bật keymon khi chưa chạy (runifnecessary) nên không trùng.
killall -9 MainUI 2>/dev/null
sleep 1

# Bật công tắc + mạch loa, mic gain. KHÔNG đổi mức âm lượng (giữ mức MainUI để lại:
# Headphone Volume=1, digital=0, DAC=140 — 2 control đầu có thang NGƯỢC so với chú thích dB).
sh "$APPDIR/set_loa_max.sh" 2>/dev/null

echo "===== Xiaozhi khoi dong $(date) =====" >> "$LOG"
HB=/tmp/xiaozhi_hb
MON=/mnt/UDISK/xiaozhi_monitor.log
rm -f "$HB"
python3 trimui_run.py >> "$LOG" 2>&1 &
APP_PID=$!

# Người gác chống treo (2026-10-08: vòng asyncio từng kẹt → MENU không ăn → phải reset cứng).
# - Nhịp tim $HB ngừng > 25 s → SIGUSR1 (app ghi stack vào /mnt/UDISK/xiaozhi_hang.log) → TERM → KILL.
# - Mỗi 10 s ghi RAM/CPU vào $MON (bộ nhớ trong, còn sau reset), giữ tối đa ~3000 dòng.
(
  start=$(date +%s); n=0
  while kill -0 "$APP_PID" 2>/dev/null; do
    sleep 5; n=$((n + 1)); now=$(date +%s)
    if [ -f "$HB" ]; then
      last=$(cut -d. -f1 "$HB" 2>/dev/null); [ -n "$last" ] || last=$now
    else
      last=$start   # chưa có nhịp tim: tính từ lúc khởi động (app nạp mất ~10–20 s)
    fi
    if [ $((now - last)) -gt 25 ] && [ $((now - start)) -gt 60 ]; then
      echo "$(date '+%F %T') TREO: nhip tim ngung $((now - last))s -> ghi stack + tat app" >> "$MON"
      kill -USR1 "$APP_PID" 2>/dev/null; sleep 2
      kill -TERM "$APP_PID" 2>/dev/null; sleep 4
      kill -9 "$APP_PID" 2>/dev/null
      break
    fi
    if [ $((n % 2)) -eq 0 ]; then
      rss=$(awk '/VmRSS/{print $2}' /proc/$APP_PID/status 2>/dev/null)
      avail=$(awk '/MemAvailable/{print $2}' /proc/meminfo)
      echo "$(date '+%F %T') app_rss_kb=$rss mem_avail_kb=$avail load=$(cut -d' ' -f1-3 /proc/loadavg) hb_tre=$((now - last))s" >> "$MON"
      if [ $((n % 120)) -eq 0 ] && [ "$(wc -l < "$MON")" -gt 3000 ]; then
        tail -n 1500 "$MON" > "$MON.tmp" && mv "$MON.tmp" "$MON"
      fi
    fi
  done
) &
WD_PID=$!

wait "$APP_PID"
kill "$WD_PID" 2>/dev/null

# App thoát (nút MENU). Vòng lặp runtrimui của hệ thống sẽ tự chạy lại MainUI.
echo "===== Xiaozhi thoat $(date) =====" >> "$LOG"
exit 0
