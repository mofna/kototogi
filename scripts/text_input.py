"""原稿の文字列やUTF-8の標準入力を受け取る。"""
from __future__ import annotations

import sys
from typing import TextIO


def normalize(text: str) -> str:
    """ファイル読取りと同じ改行・BOMの扱いにそろえる。"""
    if text.startswith("\ufeff"):
        text = text[1:]
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read_stdin(stream: TextIO | None = None) -> str:
    stream = sys.stdin if stream is None else stream
    if stream.isatty():
        raise ValueError("標準入力へ本文を渡してください。短文には --text を使えます。")
    binary = getattr(stream, "buffer", None)
    text = binary.read().decode("utf-8-sig") if binary is not None else stream.read()
    return normalize(text)


def label(value: str | None, default: str) -> str:
    name = value if value is not None else default
    if not name.strip() or any(ch in name for ch in "\r\n\x00"):
        raise ValueError("--label には表示用の名前を1行で指定してください。")
    return name


def utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
