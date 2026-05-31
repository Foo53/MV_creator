# MV Creator

AIを活用したミュージックビデオ制作設計ツール。アイデア入力から歌詞生成、映像設計、画像プロンプト生成、Remotion動画生成までを一括実行。

## インストール

```bash
pip install -e ".[dev]"
```

## 使い方

```bash
mv-creator init --project my-mv
mv-creator create-mv --project my-mv --idea "海辺の夕暮れをテーマにした失恋の歌" --provider mock
```

## Remotion動画生成

```bash
cd remotion && npm install && cd ..
mv-creator generate-timeline --project my-mv
mv-creator render-video --project my-mv
```
