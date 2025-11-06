# Productization Roadmap / プロダクト化ロードマップ

## Overview / 概要
This roadmap now references the canonical sources for configuration, security, and operations. Detailed procedures reside in `README.md`, `FEATURES.md`, `SUMMARY.md`, and the reports under the project root. 本ロードマップは実務の道筋を整理し、手順の詳細は `README.md` など公式ドキュメントへ委譲しています。

---

## Phase Guide / フェーズ別指針

### Phase 1: Architecture Consolidation / フェーズ1: アーキテクチャ統合
- **Inventory modules**: Use `SUMMARY.md` → 「実装済み機能」および `FEATURES.md` でモジュール差分を確認。
- **Single entry point**: Align CLI/サービス入口を `memo_system.py` に集約。共通処理は `memo_utils.py`・`memo_enhanced_utils.py` を利用し、不要派生は `IMPLEMENTATION_REPORT.md` のタスクリストに移管。
- **Migration plan**: 統合作業の進行管理は `docs/translation_workflow.md` ではなく `SUMMARY.md` → 「今後の予定」へ登録し、進捗と連動させます。

### Phase 2: Quality Foundation / フェーズ2: 品質基盤
- **Testing**: `USAGE_GUIDE.md` のシナリオに合わせて `pytest` へ移行し、`test_memo_system.py` など既存テストを拡張。
- **Static analysis**: `SYSTEM_OPTIMIZATION_REPORT.md` → 「品質管理」で追加予定の `ruff`・`mypy`・`bandit` を CI に組み込みます。
- **CI/CD**: `ci_cd_pipeline.py` と `IMPLEMENTATION_REPORT.md` の CI 項目を参照し、フェイルファスト方針を適用。

### Phase 3: Packaging & Deployment / フェーズ3: パッケージングとデプロイ
- **Metadata sync**: `pyproject.toml`・`setup.py` の管理は `README.md` → 「インストール / Installation」および `DEPLOYMENT_GUIDE.md` の記載を準拠。
- **Distributables**: 配布物の生成手順は `DEPLOYMENT_GUIDE.md` と `SUMMARY.md` → 「セキュリティレベル」に従い、署名および再現性を確保。
- **Configuration handbook**: 各 OS 向けの環境変数・ディレクトリ構成は `README.md` → 「セキュリティ設定」および `USAGE_GUIDE.md` → 「Configuration」へリンク。

### Phase 4: Documentation & UX / フェーズ4: ドキュメントとユーザー体験
- **User manual**: `README.md` をエンドユーザーガイドとし、個別ドキュメントは参照リンクのみ掲示。
- **Operational docs**: `docs/translation_workflow.md` と本ロードマップを中心に、運用手順は `SUMMARY.md` と `SYSTEM_OPTIMIZATION_REPORT.md` の該当節へ集約。
- **CLI messaging**: CLI 文言は `memo_system.py`・`memo_personal.py` のヘルプを確認し、翻訳方針は `docs/translation_workflow.md` に従って統一。

### Phase 5: Internationalization Expansion / フェーズ5: 国際化拡張
- **Language backlog**: 50言語展開は `translation_workflow.md` → 「Roadmap」セクションに追記し、`README.md` → 「今後の予定」で優先度を共有。
- **Governance**: Style guide / Glossary / Review checklist は `docs/translation_workflow.md` に統合。CI 検証は `memo_system.py` の i18n ローダー (`I18N.load_external_resources()`) をベースに追加。
- **Automation**: locales 検証ジョブの概要は `SUMMARY.md` → 「品質管理」へ反映します。

### Phase 6: Release & Support / フェーズ6: リリースとサポート
- **Release checklist**: テスト結果・翻訳 QA・セキュリティレビューは `SUMMARY.md` → 「チェックリスト」および `IMPLEMENTATION_REPORT.md` で管理。
- **Beta program**: ベータ運用方針は `docs/improvements/` 配下（例: `support_policy.md` が追加された場合）に委譲。現状は `SUMMARY.md` のロードマップ項目で追跡。
- **Support workflow**: SLA やエスカレーションは `USAGE_GUIDE.md` の運用セクションに統合予定。暫定的に本ロードマップではフラグのみ保持します。

---

## Milestones / マイルストーン
- **[M1] Foundation Complete**: Architecture tasks in `SUMMARY.md` marked complete; CI baseline from `IMPLEMENTATION_REPORT.md` green.
- **[M2] Packaging Ready**: Build artifacts reproducible per `DEPLOYMENT_GUIDE.md`; locale validation automated via pipelines defined in `translation_workflow.md`.
- **[M3] Launch Candidate**: Release checklist satisfied (`SUMMARY.md`), beta feedback logged, compliance checks reported in `SYSTEM_OPTIMIZATION_REPORT.md`.
- **[M4] General Availability**: Stable build published, support commitments recorded in future support documentation, roadmap for next cycle refreshed in `SUMMARY.md`.

---

## Next Steps / 次のアクション
- Align outstanding tasks with `SUMMARY.md` → 「今後の予定」および issue tracker。
- Keep this roadmap lean by linking to canonical docs whenever new processes are defined.
- Document decisions and outcomes in the corresponding reports to maintain a single source of truth.
