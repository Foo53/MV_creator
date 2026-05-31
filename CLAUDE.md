# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

## プロジェクト概要

MV Creator は、AIを活用したミュージックビデオ制作設計ツールです。アイデア入力から歌詞生成、映像設計、画像プロンプト生成、Remotion動画生成までを一括実行します。実際の画像生成は行わず、プロンプトのみを出力します。

UIとLLMプロンプトはすべて日本語です。

## よく使うコマンド

```bash
# インストール（編集可能モード、dev依存込み）
pip install -e ".[dev]"

# テスト実行（どちらでも可）
python -m unittest discover -s tests
python -m pytest

# テストを1件だけ実行
python -m pytest tests/test_pipeline.py::PipelineTest::test_mock_provider_structured_brief

# mock providerでCLI実行（APIキー不要）
mv-creator init --project my-mv
mv-creator create-mv --project my-mv --idea "海辺の夕暮れをテーマにした失恋の歌" --provider mock

# Geminiで実行
mv-creator create-mv --project my-mv --idea "アイデア" --provider gemini --model gemini-2.5-flash

# Remotion動画生成
cd remotion && npm install && cd ..
mv-creator generate-timeline --project my-mv
mv-creator render-video --project my-mv

# Web UI起動
mv-creator web --port 8000
```

## アーキテクチャ

**パイプラインの流れ**（`pipeline.py`で定義）:
1. `IdeationAgent` → `LyricAgent` → `CharacterAgent` → `ScenePlannerAgent` → `ShotDirectorAgent` → `PromptEngineerAgent`
2. `ContinuityCriticAgent`が制作設計全体を評価し、問題があれば`RevisionAgent`が修正方針を提示
3. 画像生成はプロンプトのみ出力（実際の画像生成は行わない）
4. Remotion用タイムライン生成と動画レンダリング

全エージェントは`agents.py`の`Agent`を継承し、`LLMProvider`を受け取り、Pydanticモデルを返します。エージェント間の一貫性を保つため、`RAGStore`インスタンスを受け取って参照・書き込みを行います。

**各モジュールの役割:**

- `cli.py` — argparseベースのCLI。サブコマンド: `init`, `create-mv`, `generate-timeline`, `render-video`, `rebuild-mv-visuals`, `web`, `inspect-rag`, `revise`
- `pipeline.py` — エージェントを順次実行し、プロジェクト初期化と出力書き込みを管理
- `agents.py` — 各エージェントクラスは単一のLLM呼び出しとプロンプトテンプレートをラップ。実行中にRAGへ書き込む
- `providers.py` — `LLMProvider`抽象クラスと、`GeminiProvider`（`response_schema`による構造化出力）および`MockProvider`（全スキーマ型の決定論的フィクスチャ）。`normalize_aspect_ratio()`は未対応比率（例: `2.35:1` → `21:9`）をGemini対応比率へ丸める
- `models.py` — 全Pydanticデータモデル（`ProductionBrief`, `ProductionDesign`, `ShotPlan`など）と`ProjectPaths`
- `schemas.py` — エージェントの構造化出力タゲットとなるラッパーモデル（`ScriptList`, `ShotList`, `PromptBundle`など）
- `rag.py` — `RAGStore`によるキーワードベース検索。キャラクター、ショット、プロンプト、画像メタデータを`MemoryRecord`として保存。全検索は`trace`に記録されRAG参照履歴出力に使われる
- `renderers.py` — `ProductionDesign`をMarkdownファイルに変換し、JSON出力を書き込む
- `web_app.py` — FastAPIベースのWeb UI。ブラウザからMV制作設計を実行可能

**出力構造**は`outputs/<project>/`以下に配置。`design.json`, `design.md`, `storyboard.md`, `image_prompts.md`, `video_prompts.md`, `continuity_report.md`, `rag_trace.md`, `learning_notes.md`, `timeline.json`, `images/`。

## 開発上の注意

- Python 3.10+、全ファイルで`from __future__ import annotations`を使用
- `--provider gemini`には`GEMINI_API_KEY`環境変数が必要。mock providerはオフラインで動作
- Mock providerはPydanticモデルのクラス名をキーに決定論的データを返す — 新しいエージェント戻り値型を追加する際は`providers.py`の`_mock_payload()`にケースを追加する必要がある
- テストは`tempfile.TemporaryDirectory`を使い、`cli.main()`にargvリストを直接渡して実行
- `pyproject.toml`で`pythonpath = ["src"]`を設定済み。テスト内の`sys.path.insert`は旧来のフォールバック
- Remotionプロジェクトは`remotion/`ディレクトリに配置。`npm install`後に`render-video`コマンドで動画生成

## 言語

すべての出力（会話、説明、コメント、コミットメッセージ）は**日本語**。コード内変数名・関数名は英語可。
