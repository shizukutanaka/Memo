# Memo 改善レーン報告（拡大 Wave 1）

日付: 2026-11-28
ブランチ: `exp/memo`
ベース: `e4e931e` (`origin/main`)

## 1. ベースライン（pristine な main）

環境準備前に `python` / `pytest` が実行環境へ入っていなかったため、repo 外の `/tmp/memo-exp-venv` を作成し、`-e .`・`pytest`・`pytest-cov`・`pytest-asyncio`・`click` を入れて実行した。repo の依存宣言自体には変更していない。

実行コマンド:

```sh
python3 -m pytest tests/ test_memo_core_suite.py test_memo_system.py test_search_fts.py -v --tb=short --cov-report=xml --cov-report=term-missing
```

実際には venv 内の Python (`/tmp/memo-exp-venv/bin/python`, Python 3.12.3, pytest 9.2.0) を使用した。

結果:

- collected: 127
- passed: 126
- skipped: 1（`test_memo_system.py:139`、Cryptography 未インストールによる既存 skip）
- failed: 0
- coverage: `memo.py` 29.56%（fail-under 20% を通過）

結論: baseline は緑だったため、「緑に戻す」ではなく実在欠陥 1 件の改善に進んだ。

## 2. 不変条件固定テストの事前確認

対象候補パスについて grep した結果、`create_backup` / `restore_backup` / `list_backups` は `tests/test_public_api.py` の公開 API 契約リストに名前だけ出る。backup ファイルの存在/不在・件数・生ファイル構造を固定するテストは見つからなかった。したがって、バックアップの内部実装を SQLite API へ換えても、このリポジトリの不変条件文化を壊さないと判断した。

## 3. マスク思考法 + ソクラテス問答で当てた視点

- ローカルサーバーの Host/Origin 検証: 出荷対象の `memo.py` に HTTP サーバー実装が見つからず、適用できなかった。実在しない問題を発明しないため対象外。
- 秘密・複製ファイルの権限: `~/.memo` は `0o700`、session secret 等は別系統で `0o600` 化済みだった。今回の実測では、これよりバックアップ破損のほうが直接的だった。
- 保存データの無検証な信用: `templates.json` は JSON かつ top-level dict かだけ見ており、値の schema は無検証だった。ただし壊れた場合の影響はテンプレート機能に限られ、memo 本体の消失より優先度は低いと判断した。
- 無言の失敗: `list_all` / `search` 等は例外をログへ出しつつ空配列を返す。利用者には失敗と0件が区別できない可能性があるが、公開 API の意味論変更を伴い、今回の 1 件としては広すぎると判断した。
- 記録と実態のずれ: `pytest.ini` の coverage コメントは修復時点の 21% を説明する歴史的記述で、現在値 29.56% と必ずしも矛盾しない。最優先ではないと判断した。
- データ消失リスク: `templates.json` の非 atomic 上書きも残っているが、memo 本体の backup/restore が実測で壊れているほうが重大だった。

ソクラテス問答の要点:

- なぜ壊れていると言えるか: SQLite は WAL モードで動いており、コミット済みデータが main DB ファイルではなく WAL に残る状態を作れる。この状態で main DB だけを `shutil.copy2` すると、そのコミットはバックアップへ入らない。
- 反証は何か: 通常は `_checkpoint_wal("passive")` により main DB へ反映される可能性がある。しかし、先に開始した正当な concurrent reader がいると checkpoint は reader の read mark を越えられず、WAL に残る。実測でもこの反証は崩れた。
- やめたら何が起きるか: backup にはコミット済み memo が入らず、restore は `True` を返しながら古い WAL の影響で復元前状態が残る。利用者は成功表示を信じてデータを失う。

## 4. 最優先項目と根拠（実測）

選んだ 1 件: **WAL モードの SQLite database を生ファイルコピーする backup/restore が、コミット済みデータを欠落・復元失敗させる欠陥**。

backup 側の再現（main、修正前）:

```text
wal_exists_after_add True wal_size 57712
live_count 1
backup_count 0
```

つまり live DB にはコミット済み memo が 1 件あるのに、作成された backup には 0 件しかなかった。

restore 側の再現（修正前の raw copy 相当）:

```text
restore_ok True
count_after_restore 1
wal_exists True
count_after_reader_close 1
```

空 backup から restore して `True` が返っているのに、post-backup memo が残っていた。期待値は 0 件。

追加した退行テストも修正前に赤を確認した:

- `test_backup_includes_commit_visible_only_in_wal`: `rows == []` となり、追加した memo が backup に無かった。
- `test_restore_replaces_commit_visible_only_in_wal`: `count == 1` となり、空 backup への復元後も post-backup memo が残った。

## 5. 変更内容

変更ファイル:

- `memo.py`
- `tests/test_memo_core.py`

実装内容:

1. `MemoStore._copy_sqlite_database()` を追加し、SQLite online backup API (`sqlite3.Connection.backup`) で database をコピーするようにした。これにより main DB ファイルだけでなく、WAL 内のコミット済み変更を含む一貫した内容がコピーされる。
2. `create_backup()` は backup を一度 `mkstemp` の一時ファイルへ作り、成功後に `os.replace()` で目的の backup 名へ置き換えるようにした。失敗時は一時ファイルを削除し、部分コピーを正規 backup として残さない。
3. `restore_backup()` も raw copy をやめ、同じ SQLite online backup API で backup の内容を live DB へ適用するようにした。復元失敗時の safety backup 復帰も同じ API を使う。
4. 退行テストを 2 件追加した。concurrent reader が WAL 保持を強制する状態で、(a) backup がコミット済み memo を含むこと、(b) restore が post-backup memo を確実に取り除くことを固定する。

新規の実行時依存追加: なし。`sqlite3`・`tempfile`・`os` は標準ライブラリ / 既存 import。

## 6. 変更後の検証

対象テスト:

```text
tests/test_memo_core.py::TestBackupConsistency ..  [2 passed]
```

CI と同じ全テスト:

```sh
/tmp/memo-exp-venv/bin/python -m pytest tests/ test_memo_core_suite.py test_memo_system.py test_search_fts.py -v --tb=short --cov-report=xml --cov-report=term-missing
```

結果:

- collected: 129
- passed: 128
- skipped: 1（baseline と同じ Cryptography 未インストール skip）
- failed: 0
- coverage: `memo.py` 30.43%（fail-under 20% を通過）

品質ゲートも実行した:

- `black --check memo.py memo_tui.py cloud_sync.py --line-length=100`: pass
- `isort --check-only memo.py memo_tui.py cloud_sync.py`: pass
- `mypy memo.py --ignore-missing-imports`: pass
- `flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics`: pass（0件）

## 7. 未検証項目・残課題

- Linux/Python 3.12.3 でのみ検証した。Windows/macOS と Python 3.9-3.13 全体の matrix は未実行。
- restore の途中でプロセスが落ちるケース、非常に大きい DB での同時書き込み負荷は未検証。今回の修正は raw copy より安全だが、運用上の中断耐性まで保証するものではない。
- CI の `bandit` / `pip-audit` / `python -m build` は今回実行していない。変更は標準ライブラリ内の copy 方式差し替えで新規依存はない。
- `templates.json` の非 atomic 上書き、top-level dict だけを信用する template schema、検索/一覧 API が例外時に空配列を返す設計は未着手。いずれも今回の 1 件制限のため変更していない。

## 8. 3回ルール

同一原因での失敗は 3 回に達しなかった。対象テストと全テストはいずれも初回実装修正後に合格した。
