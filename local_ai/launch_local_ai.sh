#!/bin/sh
APP_DIR=/mnt/SDCARD/Apps/XiaozhiAI
LOCK=/tmp/local-ai-launch.lock

if ! mkdir "$LOCK" 2>/dev/null; then
    echo "Trợ lý AI đang chạy; vui lòng kiểm tra /tmp/local_ai.log" >&2
    exit 1
fi

STOPPED_PIDS=""
CHILD=""

cleanup() {
    result=$?
    trap - EXIT HUP INT TERM
    if [ -n "$CHILD" ] && kill -0 "$CHILD" 2>/dev/null; then
        kill -TERM "$CHILD" 2>/dev/null
        wait "$CHILD" 2>/dev/null
    fi
    for pid in $STOPPED_PIDS; do
        kill -CONT "$pid" 2>/dev/null
    done
    rmdir "$LOCK" 2>/dev/null
    exit "$result"
}

trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

cd "$APP_DIR" || exit 1

export PATH="/mnt/SDCARD/System/bin:/usr/trimui/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export LD_LIBRARY_PATH="/mnt/SDCARD/System/lib:/usr/trimui/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PYTHONPATH="$APP_DIR/pylibs:$APP_DIR/local_ai:$APP_DIR${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
export PYTHONIOENCODING=utf-8

# Tạm dừng giao diện MainUI của máy để dành toàn quyền điều khiển màn hình và nút bấm
for pid in $(pidof MainUI); do
    state=$(awk '{print $3}' "/proc/$pid/stat" 2>/dev/null)
    case "$state" in T|t) continue;; esac
    if kill -STOP "$pid" 2>/dev/null; then
        STOPPED_PIDS="$STOPPED_PIDS $pid"
    fi
done

/mnt/SDCARD/System/bin/python3 "$APP_DIR/local_ai/app.py" --gui > /tmp/local_ai.log 2>&1 &
CHILD=$!
wait "$CHILD"
RESULT=$?
CHILD=""
exit "$RESULT"
