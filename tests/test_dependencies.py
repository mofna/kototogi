"""標準ライブラリと同梱ファイルだけで動作することを確認する。"""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TEXT = '設定を更新しました。\n\n音響班の報告では雑音を3回検出しました。筆者が再実行した結果ではありません。[S1]'


class DependencyTests(unittest.TestCase):
    def test_imports_use_standard_library_or_bundled_modules(self):
        files = [p for folder in ('scripts', 'tests', 'tools') for p in sorted((ROOT / folder).glob('*.py'))]
        bundled = {p.stem for p in files}
        unexpected = []
        for path in files:
            tree = ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name.split('.')[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module.split('.')[0]]
                else:
                    continue
                for name in names:
                    if name not in sys.stdlib_module_names and name not in bundled:
                        unexpected.append(f'{path.relative_to(ROOT)}:{node.lineno}: {name}')
        self.assertEqual(unexpected, [], '\n'.join(unexpected))

    def test_runtime_syntax_supports_python_310(self):
        for path in [p for folder in ('scripts', 'tools') for p in sorted((ROOT / folder).glob('*.py'))]:
            with self.subTest(path=path.name):
                ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path), feature_version=(3, 10))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cwd = Path(self.temp.name)

    def invoke(self, tool: str, *args: str, data: bytes | None = None):
        # Use the current interpreter by absolute path, with site packages and
        # Python environment overrides disabled. An empty PATH hides extra CLIs.
        env = dict(os.environ, PATH='')
        return subprocess.run(
            [sys.executable, '-E', '-S', '-B', str(ROOT / 'scripts' / tool), *args],
            cwd=self.cwd, input=data, capture_output=True, env=env, timeout=30,
        )

    def decoded(self, result, expected: int = 0):
        self.assertEqual(result.returncode, expected, result.stderr.decode('utf-8'))
        return json.loads(result.stdout)

    def test_lint_file_text_and_stdin_without_site_packages(self):
        path = self.cwd / 'article.md'
        path.write_text(TEXT, encoding='utf-8')
        file_result = self.decoded(self.invoke('lint.py', str(path), '--json'))
        text_result = self.decoded(self.invoke('lint.py', '--text', TEXT, '--label', str(path), '--json'))
        stdin_result = self.decoded(self.invoke('lint.py', '--stdin', '--label', str(path), '--json', data=TEXT.encode('utf-8')))
        self.assertEqual(file_result, text_result)
        self.assertEqual(file_result, stdin_result)

    def test_text_comparison_without_site_packages(self):
        result = self.decoded(self.invoke(
            'check.py', 'text', '--source-text', '待ち時間を30ms短縮しました。',
            '--text', '待ち時間をなくしました。', '--material-text', '短縮は30msでした。', '--json',
        ))
        self.assertTrue(result['comparison']['findings'])
        self.assertEqual(list(self.cwd.iterdir()), [])

    def test_required_rewrite_without_site_packages(self):
        result = self.decoded(self.invoke('check.py', 'text', '--text', TEXT, '--json'), expected=1)
        self.assertFalse(result['editorial']['ready'])
        self.assertTrue(result['editorial']['required_rewrites'])

    def test_file_check_and_verify_without_site_packages(self):
        source = self.cwd / 'original.md'
        final = self.cwd / 'final.md'
        record = self.cwd / 'review.json'
        source.write_text('設定は、有効です。', encoding='utf-8')
        final.write_text('設定は有効です。', encoding='utf-8')
        result = self.decoded(self.invoke(
            'check.py', 'run', '--source', str(source), '--final', str(final),
            '--record', str(record), '--json',
        ))
        self.assertTrue(result['editorial']['ready'])
        verified = self.decoded(self.invoke('check.py', 'verify', '--final', str(final), '--record', str(record), '--json'))
        self.assertTrue(verified['file_match'])
        self.assertTrue(verified['editorial_ready'])


if __name__ == '__main__':
    unittest.main()
