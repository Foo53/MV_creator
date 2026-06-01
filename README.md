# MV Creator

MV Creator は、短いアイデアからミュージックビデオの制作設計を組み立てる Python 製ツールです。
LLM を複数のエージェントとして段階的に呼び出し、Suno 用の歌詞・style、楽曲構成、映像方針、MVビート、キャラクター、シーン、ショット、画像生成プロンプトを生成します。

生成した静止画と任意の BGM を用意すると、Remotion で歌詞字幕付き MP4 を組み立てられます。

## 静止画MVとしての設計

このツールは、動画生成モデルで各カットを作る方式ではなく、ChatGPT で生成した一枚絵を音楽に合わせて編集する静止画MVに特化しています。

- 各ショットは、複数カットや連続動作を詰め込まない一枚絵として設計します。
- 各画像に、MV全体での役割、構図、注視点、字幕用の余白、表示尺を持たせます。
- Remotion では、穏やかなパン・ズーム、ホールド、クロスフェードを使って静止画に動きを与えます。
- 歌詞字幕は、各画像が表示される時間帯と重なる曲セクションから割り当てます。
- ChatGPT 用画像プロンプトでは、分割画面、コラージュ、絵コンテ、画像内テキスト、ロゴ、透かしを避けるよう指定します。

## できること

- アイデアから曲、画像プロンプト、静止画MV動画を作る制作モード
- 入力済みの歌詞から画像プロンプト、静止画MV動画を作る制作モード
- アイデアから MV 制作ブリーフを生成
- Suno 向けのメタタグ付き歌詞と style パラメータを生成
- 歌詞を Intro、Verse、Chorus、Bridge、Outro などのセクションへ分解
- 楽曲構成に合わせた MV の映像方針、MVビート、キャラクター、シーン、ショットを生成
- ショットごとの画像生成プロンプトと静止画MV編集メモを生成
- キャラクター、ショット、プロンプトを簡易 RAG ストアへ保存し、後続エージェントで参照
- 継続性評価を実行し、矛盾や改善案をレポート
- 静止画、BGM、歌詞字幕を Remotion で MP4 に組み立て
- CLI と FastAPI ベースの Web UI を提供

## 現在の実装範囲

このリポジトリは MV の設計と静止画ベースの動画編集を扱います。

- Suno の API を直接呼び出して音楽を生成する機能はありません。生成された歌詞と style を Suno へ入力し、完成した音源を別途用意してください。
- 画像生成 API を直接呼び出す機能はありません。出力されたプロンプトを使って画像を生成し、所定の場所へ配置してください。
- 継続性評価後の修正エージェントは改善方針を記録しますが、設計データを自動修正しません。
- Web UI では、制作設計の生成、Suno パラメータの編集、音源アップロード、ChatGPT 用画像プロンプトのコピー、生成画像のアップロード、タイムライン生成、Remotion レンダリングを操作できます。

## 必要環境

- Python 3.10 以上
- Node.js 18 以上と npm
- Gemini を使う場合: `GEMINI_API_KEY`
- Claude Code CLI を使う場合: `claude` コマンド
- Codex CLI を使う場合: `codex` コマンドとログイン済みのCodex CLI

## インストール

```bash
pip install -e ".[dev]"
cd remotion
npm install
cd ..
```

## クイックスタート

API キーが不要な `mock` Provider で制作設計を生成できます。

### アイデアから曲・画像・動画を作る

歌詞と Suno style を生成し、その曲に合わせて静止画MVを設計します。

```bash
mv-creator create-mv \
  --project my-mv \
  --idea "海辺の夕暮れをテーマにした失恋の歌" \
  --provider mock
```

### 入力済み歌詞から画像・動画を作る

歌詞生成を飛ばし、入力した歌詞をそのまま使って静止画MVを設計します。`--music-style` は任意です。

```bash
mv-creator create-mv-from-lyrics \
  --project lyrics-mv \
  --lyrics "[Verse 1]
雨の街を歩いている

[Chorus]
光を探している

[End]" \
  --music-style "J-Pop, mid-tempo, piano and synth, emotional vocals" \
  --provider mock
```

出力は `outputs/my-mv/` に作成されます。

## 実際の MV を組み立てる

### 1. 音楽を用意する

`outputs/my-mv/design.md` または `outputs/my-mv/design.json` に出力された Suno 用の歌詞と style を使って音楽を生成します。

BGM を Remotion へ組み込む場合は、`outputs/my-mv/design.json` の `suno_params.audio_path` にプロジェクトルートからの相対パスを設定します。Web UI の音楽設定画面から音源をアップロードすることもできます。

例:

```text
music/bgm.mp3
```

### 2. 静止画を配置する

ショットごとの画像生成プロンプトは `outputs/my-mv/image_prompts.md` に出力されます。
各プロンプトは ChatGPT で一枚の完成画像を生成するためのものです。画像内に歌詞字幕を描かせる必要はありません。字幕は Remotion が動画書き出し時に重ねます。
生成した画像は、次のいずれかの規則で配置します。

```text
outputs/my-mv/images/manual/<shot_id>.png
outputs/my-mv/images/shot_001.png
outputs/my-mv/images/shot_002.png
```

`manual/<shot_id>.png` が優先されます。

### 3. タイムラインを生成してレンダリングする

```bash
mv-creator generate-timeline --project my-mv
mv-creator render-video --project my-mv
```

動画は `outputs/my-mv/videos/assembled_video.mp4` に作成されます。

## CLI

```bash
mv-creator init --project <name>
mv-creator create-mv --project <name> --idea <text> [--provider mock|gemini|claude|codex] [--model <name>]
mv-creator create-mv-from-lyrics --project <name> --lyrics <text> [--music-style <text>] [--provider mock|gemini|claude|codex] [--model <name>]
mv-creator revise --project <name> [--provider mock|gemini|claude|codex] [--model <name>]
mv-creator rebuild-mv-visuals --project <name> [--provider mock|gemini|claude|codex] [--model <name>]
mv-creator inspect-rag --project <name>
mv-creator generate-timeline --project <name>
mv-creator render-video --project <name>
mv-creator web --port 8000
```

`create-mv` と `create-mv-from-lyrics` では `--visual-style`、`--music-genre`、`--music-mood`、`--visual-palette`、`--release-format` も指定できます。楽曲尺は手入力せず、生成または入力された歌詞と曲構成から自動確定します。

`--release-format tiktok`、`instagram_reel`、`youtube_shorts` を指定すると、タイムラインは縦長の `1080x1920` になります。

## Provider

| Provider | 用途 | 備考 |
| --- | --- | --- |
| `mock` | オフラインの動作確認、テスト | 固定データを返します |
| `gemini` | 実際の LLM 生成 | `GEMINI_API_KEY` が必要です |
| `claude` | Claude Code CLI 経由の生成 | `claude -p` を実行します |
| `codex` | Codex CLI 経由の生成 | `codex exec` を読み取り専用モードで実行します |

Web UIではProviderに応じてモデル候補が切り替わります。Codexの候補は `~/.codex/models_cache.json` の公開モデルから読み込みます。CLIでCodexを使う例:

```bash
mv-creator create-mv \
  --project codex-mv \
  --idea "夜明け前の高速道路を走る失恋の歌" \
  --provider codex \
  --model gpt-5.5
```

## 生成物

主なファイルは `outputs/<project>/` に出力されます。

| ファイル | 内容 |
| --- | --- |
| `design.json` | 制作設計の構造化データ |
| `design.md` | 制作ブリーフ、音楽、映像方針、キャラクター、シーン |
| `storyboard.md` | ショットごとの絵コンテ |
| `image_prompts.md` | 画像生成プロンプト |
| `editing_prompts.md` | Remotion のパン・ズーム、ホールド、クロスフェード用編集メモ |
| `continuity_report.md` | 継続性の指摘 |
| `rag_store.json` | 簡易 RAG ストア |
| `rag_trace.md` | RAG の参照履歴 |
| `timeline_manifest.json` | Remotion 用タイムライン |
| `videos/assembled_video.mp4` | レンダリングされた動画 |

## Web UI

```bash
mv-creator web --port 8000
```

ブラウザで `http://127.0.0.1:8000` を開きます。

Web UI では、アイデア入力モードと歌詞入力モードを選べます。制作設計を作成した後、Suno で生成した音源と ChatGPT で生成した画像をアップロードして、Remotion の動画書き出しまで進められます。

## テスト

```bash
python -m pytest
```

## 既知の制約

- タイムラインの尺は、歌詞生成時の推定尺と曲構成分析で得た各セクションの合計秒数から自動確定されます。アップロードした BGM ファイル自体の再生時間は解析しないため、実音源と細かく合わせる場合は `timeline_manifest.json` を調整してください。
- 歌詞セクションは想定尺と画像の表示区間に基づいてショットへ割り当てられます。細かな同期が必要な場合は `timeline_manifest.json` を調整してください。
- `render-video` は実行時のカレントディレクトリ配下にある `remotion/` を参照します。リポジトリルートで実行してください。
