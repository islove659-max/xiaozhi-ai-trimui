"""Mô-đun phát âm thanh giọng nói tiếng Việt (TTS) cho máy TrimUI Brick Pro.
Sử dụng công nghệ chuyển văn bản thành giọng nói tiếng Việt tự nhiên và phát trực tiếp qua ALSA PlaybackDmix.
"""

import os
import re
import ssl
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path


def get_ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class VoicePlayer:
    def __init__(self, cache_dir: Path | None = None):
        if cache_dir is None:
            self.cache_dir = Path(__file__).resolve().parent / "audio_cache"
        else:
            self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._current_process = None
        self._stop_requested = False
        self._is_speaking = False
        self._lock = threading.Lock()

    @property
    def is_speaking(self) -> bool:
        return self._is_speaking

    def stop(self):
        """Ngắt âm thanh đang phát ngay lập tức (khi bấm nút B)."""
        self._stop_requested = True
        with self._lock:
            if self._current_process and self._current_process.poll() is None:
                try:
                    self._current_process.terminate()
                    time.sleep(0.05)
                    if self._current_process.poll() is None:
                        self._current_process.kill()
                except Exception:
                    pass
                self._current_process = None
        self._is_speaking = False

    def _split_text(self, text: str) -> list[str]:
        """Tách câu dài thành các cụm từ ngắn dưới 120 ký tự để tải TTS mượt mà."""
        text = re.sub(r"[\*\#\-\_]", "", text)  # Bỏ ký tự markdown
        # Tách theo dấu câu
        parts = re.split(r"(?<=[.!?,;:])\s+", text.strip())
        chunks = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if len(part) <= 120:
                chunks.append(part)
            else:
                words = part.split()
                cur = ""
                for w in words:
                    if len(cur) + len(w) + 1 <= 120:
                        cur = f"{cur} {w}".strip()
                    else:
                        if cur:
                            chunks.append(cur)
                        cur = w
                if cur:
                    chunks.append(cur)
        return chunks

    def speak(self, text: str, on_start=None, on_finish=None):
        """Chạy phát âm thanh trong luồng riêng để không chặn giao diện."""
        threading.Thread(target=self._speak_worker, args=(text, on_start, on_finish), daemon=True).start()

    def _speak_worker(self, text: str, on_start=None, on_finish=None):
        self.stop()
        self._stop_requested = False
        self._is_speaking = True

        if on_start:
            try:
                on_start()
            except Exception:
                pass

        chunks = self._split_text(text)
        ctx = get_ssl_context()

        for chunk in chunks:
            if self._stop_requested:
                break
            try:
                # Tải audio Google TTS tiếng Việt
                encoded = urllib.parse.quote(chunk)
                url = f"https://translate.google.com/translate_tts?ie=UTF-8&tl=vi&client=tw-ob&q={encoded}"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Linux; Android 10)"})
                with urllib.request.urlopen(req, timeout=5, context=ctx) as resp:
                    audio_data = resp.read()

                if self._stop_requested or not audio_data:
                    break

                # Sử dụng pipeline: ffmpeg giải mã -> aplay phát ra ALSA
                # Trên máy TrimUI, còi/loa dùng PlaybackDmix
                cmd = "ffmpeg -i - -ar 48000 -ac 2 -f wav - 2>/dev/null | aplay -D PlaybackDmix -q 2>/dev/null"
                with self._lock:
                    if self._stop_requested:
                        break
                    proc = subprocess.Popen(
                        cmd,
                        shell=True,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    self._current_process = proc

                proc.communicate(input=audio_data)

            except Exception:
                # Nếu không có mạng hoặc lỗi phát, chuyển sang câu tiếp
                pass

        self._is_speaking = False
        with self._lock:
            self._current_process = None

        if on_finish:
            try:
                on_finish()
            except Exception:
                pass
