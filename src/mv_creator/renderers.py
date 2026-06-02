from __future__ import annotations

from pathlib import Path

from mv_creator.models import ProductionDesign


def write_all_outputs(design: ProductionDesign, root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "design.json").write_text(design.model_dump_json(indent=2), encoding="utf-8")
    (root / "design.md").write_text(render_design(design), encoding="utf-8")
    (root / "storyboard.md").write_text(render_storyboard(design), encoding="utf-8")
    (root / "image_prompts.md").write_text(render_image_prompts(design), encoding="utf-8")
    (root / "editing_prompts.md").write_text(render_editing_prompts(design), encoding="utf-8")
    (root / "video_prompts.md").unlink(missing_ok=True)
    (root / "continuity_report.md").write_text(render_continuity(design), encoding="utf-8")
    (root / "rag_trace.md").write_text(render_rag_trace(design), encoding="utf-8")
    (root / "learning_notes.md").write_text(render_learning_notes(design), encoding="utf-8")


def render_design(design: ProductionDesign) -> str:
    lines = [
        f"# {design.brief.title}",
        "",
        "## ログライン",
        design.brief.logline,
        "",
        "## 制作ブリーフ",
        f"- MVビジュアルスタイル: {design.brief.visual_style}",
        f"- 想定尺: {design.brief.duration_seconds}秒",
        f"- 制作モード: {design.creation_mode}",
    ]
    if design.brief.music_genre:
        lines.append(f"- 楽曲ジャンル: {design.brief.music_genre}")
    if design.brief.music_mood:
        lines.append(f"- 楽曲ムード: {design.brief.music_mood}")
    if design.brief.visual_palette:
        lines.append(f"- MVカラーパレット: {design.brief.visual_palette}")
    if design.brief.release_format:
        lines.append(f"- 公開フォーマット: {design.brief.release_format}")
    lines.extend([
        f"- テーマ: {', '.join(design.brief.themes)}",
        "",
    ])
    if design.suno_params:
        lines.extend([
            "## Suno音楽パラメータ",
            f"- Style: {design.suno_params.style}",
            f"- Weirdness: {design.suno_params.weirdness}",
            f"- Style Influence: {design.suno_params.style_influence}",
            f"- Audio Influence: {design.suno_params.audio_influence}",
            "",
            "### Lyrics",
            design.suno_params.lyrics,
            "",
        ])
    if design.song_sections:
        lines.extend(["## 曲構成分析", ""])
        for section in design.song_sections:
            lines.extend(
                [
                    f"### {section.label}",
                    f"- Mood: {section.mood}",
                    f"- Visual intent: {section.visual_intent}",
                    f"- Estimated duration: {section.estimated_duration_seconds}秒",
                    "",
                    "\n".join(section.lyrics),
                    "",
                ]
            )
    if design.mv_visual_plan:
        lines.extend(
            [
                "## MV映像方針",
                design.mv_visual_plan.concept,
                "",
                f"- Motifs: {', '.join(design.mv_visual_plan.visual_motifs)}",
                f"- Color script: {'; '.join(design.mv_visual_plan.color_script)}",
                f"- Pacing: {'; '.join(design.mv_visual_plan.pacing_notes)}",
                "",
            ]
        )
    if design.characters:
        lines.extend(["## キャラクター", ""])
        for character in design.characters:
            lines.extend(
                [
                    f"### {character.name}",
                    f"- 役割: {character.role}",
                    f"- 性格: {character.personality}",
                    f"- 外見: {character.appearance}",
                    f"- 衣装: {character.wardrobe}",
                    f"- 継続性メモ: {'; '.join(character.continuity_notes)}",
                    "",
                ]
            )
    if design.scenes:
        lines.extend(["## シーン", ""])
        for scene in design.scenes:
            lines.extend(
                [
                    f"### {scene.scene_id}: {scene.title}",
                    f"- 場所: {scene.location}",
                    f"- 時間帯: {scene.time_of_day}",
                    f"- 概要: {scene.summary}",
                    f"- 登場人物: {', '.join(scene.characters)}",
                    "",
                ]
            )
    return "\n".join(lines)


def render_storyboard(design: ProductionDesign) -> str:
    lines = ["# 画像スライド設計", ""]
    for shot in design.shots:
        lines.extend(
            [
                f"## {shot.shot_id}",
                f"- 画像グループ: {shot.scene_id}",
                f"- 内容: {shot.description}",
                f"- カメラ: {shot.camera}",
                f"- レンズ: {shot.lens}",
                f"- 動き: {shot.motion}",
                f"- 静止画の役割: {shot.still_image_intent}",
                f"- 構図: {shot.composition}",
                f"- 注視点: {shot.focal_point}",
                f"- 表示尺: {shot.still_duration_seconds}秒",
                f"- トランジション: {shot.transition_type} ({shot.transition_duration_seconds}秒)",
                f"- パン・ズーム開始構図: {shot.motion_start}",
                f"- パン・ズーム終了構図: {shot.motion_end}",
                f"- 照明: {shot.lighting}",
                f"- 楽曲同期メモ: {shot.music_sync_notes}",
                "",
            ]
        )
    return "\n".join(lines)


def render_image_prompts(design: ProductionDesign) -> str:
    lines = ["# 画像生成プロンプト", ""]
    for prompt in design.image_prompts:
        lines.extend(
            [
                f"## {prompt.shot_id}",
                prompt.prompt,
                "",
                f"ネガティブプロンプト: {prompt.negative_prompt}",
                f"アスペクト比: {prompt.aspect_ratio}",
                "",
            ]
        )
    return "\n".join(lines)


def render_editing_prompts(design: ProductionDesign) -> str:
    lines = ["# 静止画MV編集メモ", ""]
    for prompt in design.editing_prompts:
        lines.extend(
            [
                f"## {prompt.shot_id}",
                prompt.editing_instruction,
                "",
                f"尺: {prompt.duration_seconds}秒",
                f"カメラ移動: {prompt.camera_motion}",
                f"時間変化メモ: {prompt.temporal_notes}",
                "",
            ]
        )
    return "\n".join(lines)


def render_continuity(design: ProductionDesign) -> str:
    lines = ["# 継続性レポート", ""]
    if not design.continuity_issues:
        lines.append("継続性の問題は検出されませんでした。")
        return "\n".join(lines)
    for issue in design.continuity_issues:
        lines.extend(
            [
                f"## {issue.severity.upper()} - {issue.location}",
                issue.issue,
                "",
                f"修正提案: {issue.recommendation}",
                "",
            ]
        )
    return "\n".join(lines)


def render_rag_trace(design: ProductionDesign) -> str:
    lines = ["# RAG参照履歴", ""]
    for item in design.rag_trace:
        lines.extend(
            [
                f"## {item.used_by}",
                f"検索クエリ: {item.query}",
                f"参照結果: {', '.join(item.results) if item.results else 'なし'}",
                "",
            ]
        )
    return "\n".join(lines)


def render_learning_notes(design: ProductionDesign) -> str:
    lines = [
        "# 学習メモ",
        "",
        "この実行では、次の生成AIエンジニアリング要素を確認できます。",
        "",
    ]
    for note in design.learning_notes:
        lines.append(f"- {note}")
    return "\n".join(lines) + "\n"
