from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from mv_creator.agents import (
    CharacterAgent,
    ContinuityCriticAgent,
    IdeationAgent,
    MVBeatPlannerAgent,
    MVVisualPlannerAgent,
    MusicAgent,
    PromptEngineerAgent,
    RevisionAgent,
    ScenePlannerAgent,
    ShotDirectorAgent,
    SongAnalysisAgent,
    build_mv_context,
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
    rag = RAGStore(paths.rag_store)
    _notify(progress, "brief", "企画整理エージェントで制作ブリーフを生成しています", 1, 11)
    brief = IdeationAgent(provider).run(idea, visual_style=visual_style, music_genre=music_genre, music_mood=music_mood, visual_palette=visual_palette, release_format=release_format)
    return _run_common(brief, provider, rag, paths, progress, creation_mode="idea_to_mv")


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
    rag = RAGStore(paths.rag_store)
    _notify(progress, "brief", "入力歌詞から静止画MVの制作ブリーフを抽出しています", 1, 10)
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
        rag,
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

    rag = RAGStore(paths.rag_store)
    _notify(progress, "song-analysis", "編集済みの歌詞とstyleを曲構成へ分解しています", 1, 7)
    song_sections = SongAnalysisAgent(provider).run(design.brief, design.suno_params)
    finalize_song_duration(design.brief, design.suno_params, song_sections)
    _notify(progress, "mv-visual-plan", "曲に準拠するMV映像方針を再生成しています", 2, 7)
    mv_visual_plan = MVVisualPlannerAgent(provider).run(design.brief, design.suno_params, song_sections)
    mv_context = build_mv_context(
        suno_params=design.suno_params,
        song_sections=song_sections,
        mv_visual_plan=mv_visual_plan,
    )

    _notify(progress, "mv-beats", "MV方針に沿ってMVビートを再生成しています", 3, 7)
    mv_beats = MVBeatPlannerAgent(provider).run(design.brief, mv_context=mv_context)
    _notify(progress, "characters", "MV方針に沿ってキャラクター設定を再生成しています", 4, 7)
    characters = CharacterAgent(provider).run(design.brief, mv_beats, rag, mv_context=mv_context)
    _notify(progress, "scenes", "歌詞セクションに沿ってシーン構成を再生成しています", 5, 7)
    scenes = ScenePlannerAgent(provider).run(design.brief, mv_beats, characters, rag, mv_context=mv_context)
    _notify(progress, "shots", "曲展開に沿ってショット設計を再生成しています", 6, 7)
    shots = ShotDirectorAgent(provider).run(design.brief, scenes, characters, rag, mv_context=mv_context)
    prompts = PromptEngineerAgent(provider).run(design.brief, shots, rag, mv_context=mv_context)

    design.mv_beats = mv_beats.items
    design.characters = characters.items
    design.scenes = scenes.items
    design.shots = shots.items
    design.image_prompts = prompts.image_prompts
    design.editing_prompts = prompts.editing_prompts
    design.song_sections = song_sections
    design.mv_visual_plan = mv_visual_plan
    design.rag_trace = rag.trace
    design.learning_notes.append("MV再設計: 編集済みのSuno歌詞・style・曲構成を上流コンテキストとして、MVビートから画像プロンプトまで再生成しました。")

    _notify(progress, "critic", "再生成したMV映像設計の一貫性を確認しています", 7, 7)
    report = ContinuityCriticAgent(provider).run(design, rag)
    design.continuity_issues = report.issues
    rag.save()
    write_all_outputs(design, paths.root)
    return design


def _run_common(
    brief,
    provider: LLMProvider,
    rag: RAGStore,
    paths: ProjectPaths,
    progress: ProgressCallback | None,
    *,
    suno_params: SunoMusicParams | None = None,
    creation_mode: str,
) -> ProductionDesign:
    total = 11 if suno_params is None else 10
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
    _notify(progress, "mv-visual-plan", "歌詞とstyleに準拠するMV映像方針を生成しています", current, total)
    mv_visual_plan = MVVisualPlannerAgent(provider).run(brief, suno_params, song_sections)
    mv_context = build_mv_context(
        suno_params=suno_params,
        song_sections=song_sections,
        mv_visual_plan=mv_visual_plan,
    )
    current += 1
    _notify(progress, "mv-beats", "曲構成に沿ってMVビートを生成しています", current, total)
    mv_beats = MVBeatPlannerAgent(provider).run(brief, mv_context=mv_context)
    current += 1
    _notify(progress, "characters", "キャラクター設計エージェントで参照情報を整理しています", current, total)
    characters = CharacterAgent(provider).run(brief, mv_beats, rag, mv_context=mv_context)
    current += 1
    _notify(progress, "scenes", "シーン設計エージェントで場面構成を作っています", current, total)
    scenes = ScenePlannerAgent(provider).run(brief, mv_beats, characters, rag, mv_context=mv_context)
    current += 1
    _notify(progress, "shots", "ショット設計エージェントでカメラと構図を作っています", current, total)
    shots = ShotDirectorAgent(provider).run(brief, scenes, characters, rag, mv_context=mv_context)
    current += 1
    _notify(progress, "prompts", "画像プロンプトと静止画MV編集メモを作っています", current, total)
    prompts = PromptEngineerAgent(provider).run(brief, shots, rag, mv_context=mv_context)

    current += 1
    _notify(progress, "design", "制作設計データを統合しています", current, total)
    design = ProductionDesign(
        brief=brief,
        mv_beats=mv_beats.items,
        characters=characters.items,
        scenes=scenes.items,
        shots=shots.items,
        image_prompts=prompts.image_prompts,
        editing_prompts=prompts.editing_prompts,
        rag_trace=rag.trace,
        learning_notes=_learning_notes(),
        suno_params=suno_params,
        song_sections=song_sections,
        mv_visual_plan=mv_visual_plan,
        creation_mode=creation_mode,
    )
    current += 1
    _notify(progress, "critic", "継続性評価エージェントで矛盾を確認しています", current, total)
    report = ContinuityCriticAgent(provider).run(design, rag)
    design.continuity_issues = report.issues
    if report.issues:
        revision = RevisionAgent(provider).run(design, rag)
        design.learning_notes.extend(f"修正ループ: {note}" for note in revision.notes)

    design.rag_trace = rag.trace
    rag.save()
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
        "エージェント設計: 企画、MVビート、キャラクター、シーン、ショット、プロンプト、評価、修正を分離しています。",
        "RAG: キャラクター、ショット、プロンプト、画像メタデータを検索し、継続性維持に使います。",
        "評価と改善: 継続性評価エージェントで最終出力前に問題点を確認します。",
        "MVモード: Sunoで音楽を生成し、歌詞字幕付きのミュージックビデオを作る設計に寄せています。",
    ]
