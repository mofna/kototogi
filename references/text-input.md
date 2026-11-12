# テキストを点検する

チャットの返答や短い報告を文字列で渡せる。ファイル入力と同じ構成・語句の診断を行い、行番号は渡した本文の先頭から数える。

## 短文

```bash
python scripts/lint.py --text "ログの出力先を変更した。"
python scripts/check.py text --text "提出する本文" --label final-response --json
```

lintは観測値と再読候補を表示する。checkのtextは再読候補と本文のハッシュを返す。前後を比べる場合は `--source-text` を添え、確認資料は `--material-text` または `--material` で指定する。

```bash
python scripts/check.py text --source-text "差分同期は次の版で追加する予定だ。" --text "差分同期を追加した。" --material-text "差分同期は次の版で追加する予定だ。" --json
```

この例では予定が実績へ変わった箇所を読み直す。

## 長文と標準入力

長文や機密情報にはUTF-8の標準入力を使う。引数で渡した本文はシェル履歴やプロセス情報に表示される場合がある。

Pythonから呼ぶ例。`message` は点検する文字列、`skill` はスキルのフォルダを表すPathとする。

```python
import json
import subprocess
import sys

result = subprocess.run(
    [sys.executable, str(skill / "scripts/check.py"), "text", "--stdin", "--json"],
    input=message, encoding="utf-8", capture_output=True, check=False,
)
if result.returncode == 2:
    raise RuntimeError(result.stderr)
report = json.loads(result.stdout)
```

PowerShellでは入出力の文字コードをそろえる。

```powershell
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$text | python -X utf8 scripts/check.py text --stdin --json
```

lintは `--stdin` と `-` の両方を受け付ける。空の文字列は0文として検査する。BOMを除き、改行をLFにそろえてから位置とハッシュを計算する。

## 結果を使う

語尾の集計は文体の観測値として使う。JSONの `polite_ending_version` は敬体の集計規則の版を示す。

通常の再読候補は前後を読んで判断する。S08は情報に合う出典表示へ整えて筆者の断りを削る。修正後の本文を再入力し、送信する文章とそろえる。

checkのtextは終了コード0で点検完了、1でS08の書換え待ち、2で入力エラーを示す。lintは候補の有無を問わず0を返し、入力エラーでは2を返す。意味の確認には本文と資料を読む。

本文や検査記録の保存は呼出し元が選ぶ。textコマンド自体は標準出力へ結果を返す。ファイルを提出する工程では従来のrunとverifyを使う。

`--self-check` はスキルなどの規則文書に使う。チャットの返答は通常モードで点検する。
