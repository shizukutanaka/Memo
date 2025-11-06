# Translation Workflow / 翻訳ワークフロー

## Overview / 概要
This workflow explains how locale resources are governed in coordination with the productization roadmap. Detailed roadmap tasks are managed in `docs/productization_roadmap.md` while this file focuses on day-to-day translation operations. 本書はロケール管理手順を整理し、ロードマップ(`docs/productization_roadmap.md`)と連携して翻訳ガバナンスを維持します。

---

## Directory Layout / ディレクトリ構成
- **`locales/`**: 言語別 JSON（例: `en.json`, `ja.json`）。
- **`i18n.py`**: 組み込み辞書と外部 JSON を統合するローダー。`README.md` → 「高度な使い方」で API 利用例を確認できます。

---

## Creating a Locale File / ロケールファイルの作成
1. 既存サンプル（`locales/en.json` など）を複製。
2. `__meta__` に `language_name` と備考を設定。
3. 各キーを翻訳（未定義キーは組み込み文字列にフォールバック）。
4. ISO 639-1 コードを小文字ファイル名として保存。

対応する CLI 例やキー一覧は `FEATURES.md` と `README.md` → 「使い方」に記載されています。

---

## Validation Steps / 検証手順
- `I18N.load_external_resources()` を対象としたユニットテスト（`test_memo_system.py` 等に追加予定）を実行。
- `MEMO_LANG=<code>` を指定して CLI 動作を確認。
- JSON 構文検証は `python -m json.tool locales/<code>.json` を使用。
- ロケール整合性チェックの自動化は `docs/productization_roadmap.md` → Phase 5 で管理します。

---

## Maintenance Guidelines / 運用ガイドライン
- 翻訳キーは常に `i18n.py` と同期し、不要キーは速やかに削除。
- 新規キー追加時は組み込み辞書とサンプルロケールを同時更新。
- 他ドキュメントと重複しないように `README.md`, `SUMMARY.md` の記述と整合。
- 今後の追加計画は本節末尾と `docs/productization_roadmap.md` → Phase 5 に記録し、一元管理します。

---

## Roadmap Alignment / ロードマップ連携
- **Language prioritization**: 50言語拡張の優先順位とマイルストーンは `docs/productization_roadmap.md` の Phase 5 に従います。
- **Style guides & glossary**: スタイルガイド、用語集、レビュー手順は将来的に本ファイルへ統合予定。策定時はこの節に追記し、ロードマップへ参照を追加してください。
- **CI automation**: ロケール検証の CI 導入状況は `SUMMARY.md` → 「品質管理」で追跡します。

---

## Future Notes / 今後の予定
- Style guide / Glossary / Review checklist を策定次第、本節に追記。
- CI バリデーションステップが完成した際は、具体的なコマンドと結果確認手順を本ファイルに追加。
- 翻訳品質に関するメトリクスが定義された場合、`SYSTEM_OPTIMIZATION_REPORT.md` との連携方法を明記します。
