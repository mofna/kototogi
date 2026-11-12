# 診断ツールの利用手順

通常はAIエージェントへ原稿と依頼を渡します。ここでは同梱ツールを直接呼ぶ方法を説明します。コマンドはスキルのフォルダーから実行する例です。別の作業場所ではスクリプトと入力ファイルのパスを指定してください。

Python 3.10以降と同梱ファイルで動作します。診断処理はローカルで完結し、追加パッケージやネット接続を必要としません。文章を編集するモデルは利用する環境のものを使います。

## ファイルを点検する

原文を`original.md`に残し、校正稿を`final.md`として用意します。

```bash
python -B scripts/check.py run --source original.md --final final.md --material facts.md --record review.json
python -B scripts/check.py verify --final final.md --record review.json
```

checkのrunはlintの診断と全文差分を保存します。記録には行番号と前後の文、意味が変わった可能性のある箇所が入ります。本文を直したらrunを再実行し、提出前にverifyで検査時のファイルとの一致を確認します。

資料は`--material`で複数指定できます。原稿だけで校正する場合はこの引数を省きます。`--json`を付けると結果をJSONで受け取れます。

原文との比較を省いて候補だけを見る場合は`python -B scripts/lint.py final.md`を使います。

## 文章を直接渡す

```bash
python -B scripts/lint.py --text "検索インデックスを更新した。"
python -B scripts/check.py text --text "返答の本文" --json
python -B scripts/check.py text --source-text "校正前の文" --text "校正後の文" --json
```

長文は`--stdin`へUTF-8で渡します。`--label`は結果に付ける表示名です。点検結果は標準出力へ返ります。[テキスト入力](../references/text-input.md)にPowerShellとPythonからの呼出し例があります。

## 結果の読み方

`REVIEW`は前後を読んで判断する候補です。`REWRITE S08`は筆者の未実施を添えた断りを指します。情報に合う出典表示へ直し、再点検します。`INFO`は文体の観測値です。

checkは点検完了で0、必須修正やファイルの不一致で1、入力エラーで2を返します。lintは候補の有無を問わず0を返し、入力エラーでは2を返します。意味や事実の確認は原文と資料を読む工程で行います。

## 検査記録の保存

`review.json`には原文と校正稿の差分、資料の抜粋、実行環境の絶対パスが入ります。作業用フォルダーに保存し、共有するときは必要な情報を確認してください。スキルの配布ZIPには同梱ファイル一覧だけを収録します。

Gitリポジトリの作業を日付ごとに報告する場合は[進捗記録の点検](progress.md)を使えます。
