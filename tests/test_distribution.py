"""配布対象と文書の参照、展開後の実行を確認する。"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_release


class DistributionTests(unittest.TestCase):
    def test_manifest_lists_runtime_references_and_tests(self):
        listed = {p.relative_to(ROOT).as_posix() for p in build_release.release_files(ROOT)}
        expected = {"README.md", "SKILL.md", ".gitignore", "release-files.txt"}
        for folder, pattern in [("scripts", "*.py"), ("tools", "*.py"), ("tests", "*.py"),
                                ("references", "*.md"), ("docs", "*.md")]:
            expected.update(p.relative_to(ROOT).as_posix() for p in (ROOT / folder).glob(pattern))
        expected.add("references/features.json")
        self.assertTrue(expected <= listed, sorted(expected - listed))

    def test_documents_have_no_personal_paths(self):
        patterns = [r"(?i)\b[A-Z]:[\\/](?:Users|Documents and Settings)[\\/]",
                    r"/(?:home|Users)/[A-Za-z0-9_.-]+/", r"/mnt/data/", r"sandbox:/"]
        hits = []
        for path in build_release.release_files(ROOT):
            if path.suffix not in (".md", ".json"):
                continue
            text = path.read_text(encoding="utf-8")
            for pattern in patterns:
                if re.search(pattern, text):
                    hits.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(hits, [])

    def test_local_markdown_links_resolve(self):
        missing = []
        for path in build_release.release_files(ROOT):
            if path.suffix != ".md":
                continue
            text = path.read_text(encoding="utf-8")
            for target in re.findall(r"\[[^\]\n]+\]\(([^)\s]+)\)", text):
                if re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", target) or target.startswith("#"):
                    continue
                name = target.split("#", 1)[0]
                if name and not (path.parent / name).is_file():
                    missing.append((path.relative_to(ROOT).as_posix(), name))
        self.assertEqual(missing, [])

    def test_manifest_rejects_invalid_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("../outside.md", "/outside.md", "dir\\file.md", "README.md\nREADME.md"):
                (root / "release-files.txt").write_text(name, encoding="utf-8")
                with self.subTest(name=name), self.assertRaises(ValueError):
                    build_release.release_files(root)

    def test_archive_excludes_unlisted_files_and_checksums_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "copy"
            for source in build_release.release_files(ROOT):
                dest = root / source.relative_to(ROOT)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, dest)
            for name in ("review.json", ".codex/config.toml", "scripts/__pycache__/test.pyc",
                         "draft.md", "scripts/local_experiment.py", "audit/run.log"):
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("local-only", encoding="utf-8")
            archive_path = base / "release.zip"
            build_release.build_archive(root, archive_path)
            with zipfile.ZipFile(archive_path) as archive:
                self.assertIsNone(archive.testzip())
                names = archive.namelist()
                expected = {build_release.PREFIX + "/" + p.relative_to(root).as_posix()
                            for p in build_release.release_files(root)} | {build_release.PREFIX + "/SHA256SUMS.txt"}
                self.assertEqual(set(names), expected)
                for line in archive.read(build_release.PREFIX + "/SHA256SUMS.txt").decode("utf-8").splitlines():
                    digest, name = line.split("  ", 1)
                    self.assertEqual(hashlib.sha256(archive.read(build_release.PREFIX + "/" + name)).hexdigest(), digest)
            dest = base / "展開先 with spaces"
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(dest)
            script = dest / build_release.PREFIX / "scripts/check.py"
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
            proc = subprocess.run([sys.executable, "-S", "-B", str(script), "text",
                                   "--text", "設定を更新しました。", "--json"],
                                  cwd=base, env=env, capture_output=True, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8"))
            self.assertTrue(json.loads(proc.stdout)["editorial"]["ready"])

    def test_archive_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "release.zip"
            output.write_bytes(b"existing")
            with self.assertRaises(FileExistsError):
                build_release.build_archive(ROOT, output)
            self.assertEqual(output.read_bytes(), b"existing")

if __name__ == "__main__":
    unittest.main()
