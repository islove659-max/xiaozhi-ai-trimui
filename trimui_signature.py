"""Chữ ký tác giả bản TrimUI Hybrid của Xiaozhi AI.

Chữ ký được kiểm tra ở nhiều nơi (trimui_run.py, trimui_display.py), mỗi nơi giữ bản
mã băm riêng. Xoá/sửa chữ ký hoặc gỡ một chỗ kiểm tra thì app từ chối khởi động.
Lõi py-xiaozhi © 2025 Junsen, giấy phép MIT (xem LICENSE) — không được gỡ.
"""

import base64
import hashlib
import os
import zlib

_B = (
    "eNoBjABz/1hJQU9aSEkgQUkg4oCUIELhuqJOIFRSSU1VSSBIWUJSSUQKUGjDoXQgdHJp4buDbiAmIHR14buz"
    "IGJp4bq/biBi4bufaTogaXNsb3ZlNjU5QGdtYWlsLmNvbQpMw7VpIHB5LXhpYW96aGkgwqkgMjAyNSBKdW5z"
    "ZW4gKGdp4bqleSBwaMOpcCBNSVQpHbo3Qg=="
)
_H = "c1b4ee894a5acd2a573b1c0add62cac40a16806567fb12e6ce77fa46c55a353c"

TAMPER_MESSAGE = "Phiên bản này đã bị chỉnh sửa trái phép (chữ ký tác giả không hợp lệ)."


class SignatureError(RuntimeError):
    pass


def raw_bytes() -> bytes:
    try:
        return zlib.decompress(base64.b64decode(_B))
    except Exception as e:
        raise SignatureError(TAMPER_MESSAGE) from e


def lines() -> list[str]:
    data = raw_bytes()
    if hashlib.sha256(data).hexdigest() != _H:
        raise SignatureError(TAMPER_MESSAGE)
    return data.decode("utf-8").split("\n")


def check_authors_file(app_dir: str) -> None:
    """File AUTHORS phải còn và còn ghi người ký."""
    author = lines()[1].split(":", 1)[-1].strip()
    try:
        with open(os.path.join(app_dir, "AUTHORS"), encoding="utf-8") as f:
            if author not in f.read():
                raise SignatureError(TAMPER_MESSAGE)
    except OSError as e:
        raise SignatureError(TAMPER_MESSAGE) from e
