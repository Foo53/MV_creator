from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from mv_creator.agents import (
    ContinuityCriticAgent,
    IdeationAgent,
    MusicAgent,
    RevisionAgent,
    SlideshowPlannerAgent,
    SongAnalysisAgent,
)
from mv_creator.models import ProductionDesign, ProjectPaths, SunoMusicParams
from mv_creator.providers import LLMProvider
from mv_creator.rag import RAGStore
from mv_creator.renderers import write_all_outputs

ProgressCallback = Callable[[str, str, int, int], None]


def init_project(paths: ProjectPaths) -> None:
    paths.images.mkdir(parents=True, exist_ok=True)
    if not paths.rag_store.exists():
        paths.rag_store.write_text(json.dumps({"records": []}, ensure_ascii=False, indent=2), encoding="utf-8")
    if not paths.image_manifest.exists():
        paths.image_manifest.write_text(json.dumps({"images": []}, ensure_ascii=False, indent=2), encoding="utf-8")


def run_idea_pipeline(
    *,
    idea: str,
    project: str,
    provider: LLMProvider,
    output_root: Path,
    visual_style: str,
    music_genre: str = "",
    music_mood: str = "",
    visual_palette: str = "",
    release_format: str = "youtube",
    progress: ProgressCallback | None = None,
) -> ProductionDesign:
    paths = ProjectPaths.for_project(project, output_root)
    init_project(paths)
    _notify(progress, "brief", "企画整理エージェントで制作ブリーフを生成しています", 1, 5)
    brief = IdeationAgent(provider).run(idea, visual_style=visual_style, music_genre=music_genre, music_mood=music_mood, visual_palette=visual_palette, release_format=release_format)
    return _run_common(brief, provider, paths, progress, creation_mode="idea_to_mv")


def run_lyrics_pipeline(
    *,
    lyrics: str,
    project: str,
    provider: LLMProvider,
    output_root: Path,
    visual_style: str,
    music_style: str = "",
    music_genre: str = "",
    music_mood: str = "",
    visual_palette: str = "",
    release_format: str = "youtube",
    progress: ProgressCallback | None = None,
) -> ProductionDesign:
    paths = ProjectPaths.for_project(project, output_root)
    init_project(paths)
    _notify(progress, "brief", "入力歌詞から静止画MVの制作ブリーフを抽出しています", 1, 4)
    brief = IdeationAgent(provider).run(
        lyrics,
        visual_style=visual_style,
        music_genre=music_genre,
        music_mood=music_mood,
        visual_palette=visual_palette,
        release_format=release_format,
        source_type="lyrics",
    )
    suno_params = SunoMusicParams(lyrics=lyrics, style=music_style)
    return _run_common(
        brief,
        provider,
        paths,
        progress,
        suno_params=suno_params,
        creation_mode="lyrics_to_mv",
    )


def revise_existing_design(*, project: str, provider: LLMProvider, output_root: Path) -> ProductionDesign:
    paths = ProjectPaths.for_project(project, output_root)
    design = ProductionDesign.model_validate_json(paths.design_json.read_text(encoding="utf-8"))
    rag = RAGStore(paths.rag_store)
    report = ContinuityCriticAgent(provider).run(design, rag)
    design.continuity_issues = report.issues
    revision = RevisionAgent(provider).run(design, rag)
    design.learning_notes.extend(f"修正ループ: {note}" for note in revision.notes)
    design.rag_trace = rag.trace
    rag.save()
    write_all_outputs(design, paths.root)
    return design


def rebuild_mv_visual_design(
    *,
    project: str,
    provider: LLMProvider,
    output_root: Path,
    progress: ProgressCallback | None = None,
) -> ProductionDesign:
    paths = ProjectPaths.for_project(project, output_root)
    design = ProductionDesign.model_validate_json(paths.design_json.read_text(encoding="utf-8"))
    if design.suno_params is None:
        design.suno_params = MusicAgent(provider).run(design.brief)

    _notify(progress, "song-analysis", "編集済みの歌詞とstyleを曲構成へ分解しています", 1, 3)
    song_sections = SongAnalysisAgent(provider).run(design.brief, design.suno_params)
    finalize_song_duration(design.brief, design.suno_params, song_sections)
    _notify(progress, "slideshow", "歌詞セクションに合う画像スライドを再設計しています", 2, 3)
    slideshow = SlideshowPlannerAgent(provider).run(design.brief, design.suno_params, song_sections)

    design.mv_beats = []
    design.characters = []
    design.scenes = []
    design.shots = slideshow.shots
    design.image_prompts = slideshow.image_prompts
    design.editing_prompts = slideshow.editing_prompts
    design.song_sections = song_sections
    design.mv_visual_plan = None
    design.rag_trace = []
    design.continuity_issues = []
    design.learning_notes.append("画像スライド再設計: 編集済みのSuno歌詞・style・曲構成から、表示画像と静止画編集指示を直接再生成しました。")

    _notify(progress, "design", "画像スライド設計を保存しています", 3, 3)
    write_all_outputs(design, paths.root)
    return design


def _run_common(
    brief,
    provider: LLMProvider,
    paths: ProjectPaths,
    progress: ProgressCallback | None,
    *,
    suno_params: SunoMusicParams | None = None,
    creation_mode: str,
) -> ProductionDesign:
    total = 5 if suno_params is None else 4
    current = 2
    if suno_params is None:
        _notify(progress, "music", "Suno歌詞とstyleを生成しています", current, total)
        suno_params = MusicAgent(provider).run(brief)
        apply_preliminary_song_duration(brief, suno_params)
        current += 1
    _notify(progress, "song-analysis", "歌詞をIntro/Verse/Chorusなどの曲構成へ分解しています", current, total)
    song_sections = SongAnalysisAgent(provider).run(brief, suno_params)
    finalize_song_duration(brief, suno_params, song_sections)
    current += 1
    _notify(progress, "slideshow", "歌詞セクションに合う画像スライドを設計しています", current, total)
    slideshow = SlideshowPlannerAgent(provider).run(brief, suno_params, song_sections)
    current += 1
    _notify(progress, "design", "画像スライド設計を保存しています", current, total)
    design = ProductionDesign(
        brief=brief,
        mv_beats=[],
        characters=[],
        scenes=[],
        shots=slideshow.shots,
        image_prompts=slideshow.image_prompts,
        editing_prompts=slideshow.editing_prompts,
        rag_trace=[],
        learning_notes=_learning_notes(),
        suno_params=suno_params,
        song_sections=song_sections,
        mv_visual_plan=None,
        creation_mode=creation_mode,
    )
    write_all_outputs(design, paths.root)
    return design


def _notify(progress: ProgressCallback | None, stage: str, message: str, current: int, total: int) -> None:
    if progress is not None:
        progress(stage, message, current, total)


def apply_preliminary_song_duration(brief, suno_params: SunoMusicParams) -> None:
    brief.duration_seconds = suno_params.estimated_duration_seconds or _estimate_duration_from_lyrics(suno_params.lyrics)


def finalize_song_duration(brief, suno_params: SunoMusicParams, song_sections) -> None:
    section_duration = sum(max(0, section.estimated_duration_seconds) for section in song_sections)
    duration = section_duration or suno_params.estimated_duration_seconds or _estimate_duration_from_lyrics(suno_params.lyrics)
    brief.duration_seconds = duration
    suno_params.estimated_duration_seconds = duration


def _estimate_duration_from_lyrics(lyrics: str) -> int:
    lyric_lines = [line for line in lyrics.splitlines() if line.strip() and not line.lstrip().startswith("[")]
    section_tags = [line for line in lyrics.splitlines() if line.strip().startswith("[") and not line.strip().startswith("[End")]
    return max(30, min(900, len(lyric_lines) * 3 + len(section_tags) * 4))


def _learning_notes() -> list[str]:
    return [
        "Gemini Provider: モデル呼び出しをProvider層に閉じ込め、将来の差し替えを容易にしています。",
        "構造化出力: 各エージェントの返答をPydanticで検証できるデータにしています。",
        "軽量な画像スライド設計: 曲構成から表示画像、画像生成プロンプト、静止画編集指示を一度に生成します。",
        "静止画MVモード: Sunoで音楽を生成し、歌詞字幕付きの画像スライドショーを作る設計に寄せています。",
    ]
