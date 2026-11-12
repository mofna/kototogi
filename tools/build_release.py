#!/usr/bin/env python3
"""ファイル一覧に沿って配布ZIPを作る。"""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
from pathlib import Path, PurePosixPath
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "kototogi"


def release_files(root: Path) -> list[Path]:
    """Return listed files after validating names, presence and link targets."""
    root = root.resolve()
    result: list[Path] = []
    seen: set[str] = set()
    manifest = root / "release-files.txt"
    for line_number, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
        name = line.strip()
        if not name or name.startswith("#"):
            continue
        rel = PurePosixPath(name)
        if (rel.is_absolute() or ".." in rel.parts or "\\" in name or ":" in name
                or str(rel) != name or any(c in name for c in "\x00\r\n")):
            raise ValueError(f"一覧の{line_number}行目: 相対パスを指定してください。")
        key = name.casefold()
        if key in seen:
            raise ValueError("一覧のパスが重複しています: " + name)
        seen.add(key)
        path = root.joinpath(*rel.parts)
        for node in (path, *path.parents):
            if node == root:
                break
            if node.is_symlink() or getattr(node, "is_junction", lambda: False)():
                raise ValueError("リンクを含むパスです: " + name)
        if not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError("同梱ファイルを確認してください: " + name)
        if "__pycache__" in rel.parts or path.suffix in (".pyc", ".pyo"):
            raise ValueError("キャッシュは一覧から外してください: " + name)
        result.append(path)
    names = {p.relative_to(root).as_posix() for p in result}
    if not {"README.md", "SKILL.md", "release-files.txt"} <= names:
        raise ValueError("README.md、SKILL.md、release-files.txtを一覧へ追加してください。")
    return sorted(result)


def build_archive(root: Path, output: Path) -> dict:
    root = root.resolve()
    paths = release_files(root)
    if output.resolve().is_relative_to(root):
        raise ValueError("出力先はスキルのフォルダー外に指定してください。")
    entries: dict[str, bytes] = {}
    hashes = []
    for path in paths:
        name = path.relative_to(root).as_posix()
        data = path.read_bytes()
        entries[name] = data
        hashes.append(hashlib.sha256(data).hexdigest() + "  " + name)
    entries["SHA256SUMS.txt"] = ("\n".join(hashes) + "\n").encode("utf-8")
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(entries.items()):
            info = zipfile.ZipInfo(PREFIX + "/" + name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    data = buffer.getvalue()
    # Exclusive creation keeps an existing archive intact.
    with output.open("xb") as stream:
        stream.write(data)
    return {"files": len(entries), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build_archive(ROOT, args.output)
    except (OSError, UnicodeError, ValueError) as exc:
        parser.error(str(exc))
    print(f"ZIP: {args.output}\nFiles: {result['files']}\nSHA-256: {result['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
