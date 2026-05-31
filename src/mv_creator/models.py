from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProductionBrief(BaseModel):
    title: str = Field(description="作品タイトル")
    logline: str = Field(description="作品の短い説明")
    audience: str = Field(default="general", description="想定視聴者")
    style: str = Field(default="cinematic", description="映像スタイル")
    duration_seconds: int = Field(default=60, description="想定尺")
    output_mode: Literal["mv"] = Field(default="mv", description="出力モード")
    genre: str = Field(default="", description="作品ジャンル")
    mood: str = Field(default="", description="雰囲気・ムード")
    color_tone: str = Field(default="", description="色調")
    narration_style: str = Field(default="", description="ナレーション・字幕の文体")
    target_platform: str = Field(default="", description="想定配信プラットフォーム")
    themes: list[str] = Field(default_factory=list, description="テーマ")
    visual_rules: list[str] = Field(default_factory=list, description="映像上の一貫性ルール")
    negative_constraints: list[str] = Field(default_factory=list, description="避けるべき表現")


class CharacterProfile(BaseModel):
    id: str
    name: str
    role: str
    personality: str
    appearance: str
    wardrobe: str
    voice: str = ""
    continuity_notes: list[str] = Field(default_factory=list)


class ScriptBeat(BaseModel):
    beat_id: str
    summary: str
    dialogue: list[str] = Field(default_factory=list)
    emotional_purpose: str


class ScenePlan(BaseModel):
    scene_id: str
    title: str
    location: str
    time_of_day: str
    summary: str
    characters: list[str] = Field(default_factory=list)
    beats: list[ScriptBeat] = Field(default_factory=list)
    continuity_requirements: list[str] = Field(default_factory=list)


class ShotPlan(BaseModel):
    shot_id: str
    scene_id: str
    order: int
    description: str
    camera: str
    lens: str
    motion: str
    first_frame: str
    last_frame: str
    lighting: str
    audio: str
    referenced_memory: list[str] = Field(default_factory=list)
    narration_caption: str = Field(default="", description="MV字幕用テキスト")
    still_image_intent: str = Field(default="", description="静止画MVでこの一枚が担う役割")
    composition: str = Field(default="", description="一枚絵としての構図と余白")
    focal_point: str = Field(default="center", description="パン・ズームで注目させる被写体や位置")
    still_duration_seconds: float = Field(default=5.0, gt=0, description="静止画MVでこの一枚を表示する秒数")
    transition_type: Literal["crossfade", "cut"] = Field(default="crossfade", description="次の静止画への切り替え")
    transition_duration_seconds: float = Field(default=0.6, ge=0, le=3, description="クロスフェード秒数")


class ImagePrompt(BaseModel):
    shot_id: str
    prompt: str
    negative_prompt: str = ""
    aspect_ratio: str = "16:9"
    style_tags: list[str] = Field(default_factory=list)


class VideoPrompt(BaseModel):
    shot_id: str
    prompt: str
    duration_seconds: int = 5
    camera_motion: str
    temporal_notes: str


class ContinuityIssue(BaseModel):
    severity: Literal["low", "medium", "high"]
    location: str
    issue: str
    recommendation: str


class SunoMusicParams(BaseModel):
    lyrics: str = Field(description="Suno向けメタタグ付き歌詞")
    style: str = Field(default="", description="SunoのStyle指定")
    weirdness: int = Field(default=50, description="Suno Weirdness (0-100)")
    style_influence: int = Field(default=80, description="Suno Style Influence (0-100)")
    audio_influence: int = Field(default=50, description="Suno Audio Influence (0-100)")
    audio_path: str | None = Field(default=None, description="保存済み音楽ファイルの相対パス")


class SongSection(BaseModel):
    section_id: str = Field(description="Suno歌詞内のセクションID")
    label: str = Field(description="Intro、Verse、Chorusなどのセクション名")
    lyrics: list[str] = Field(default_factory=list, description="このセクションに含まれる歌詞行")
    mood: str = Field(default="", description="このセクションの感情・雰囲気")
    visual_intent: str = Field(default="", description="このセクションで映像が担う役割")
    estimated_duration_seconds: int = Field(default=0, description="想定尺")


class MVVisualPlan(BaseModel):
    concept: str = Field(description="曲から導いたMV全体の映像コンセプト")
    visual_motifs: list[str] = Field(default_factory=list, description="繰り返し使う象徴・モチーフ")
    color_script: list[str] = Field(default_factory=list, description="曲構成に沿った色味の推移")
    pacing_notes: list[str] = Field(default_factory=list, description="曲のテンポ・展開に合わせた編集方針")
    section_to_visuals: dict[str, str] = Field(default_factory=dict, description="歌詞セクションごとの映像方針")


class RAGTraceItem(BaseModel):
    query: str
    results: list[str] = Field(default_factory=list)
    used_by: str


class ProductionDesign(BaseModel):
    brief: ProductionBrief
    script: list[ScriptBeat]
    characters: list[CharacterProfile]
    scenes: list[ScenePlan]
    shots: list[ShotPlan]
    image_prompts: list[ImagePrompt]
    video_prompts: list[VideoPrompt]
    continuity_issues: list[ContinuityIssue] = Field(default_factory=list)
    rag_trace: list[RAGTraceItem] = Field(default_factory=list)
    learning_notes: list[str] = Field(default_factory=list)
    suno_params: SunoMusicParams | None = Field(default=None, description="MVモード時のSuno音楽生成パラメータ")
    song_sections: list[SongSection] = Field(default_factory=list, description="MVモードで歌詞を曲構成に分解した結果")
    mv_visual_plan: MVVisualPlan | None = Field(default=None, description="MVモードで曲から導いた映像設計方針")
    creation_mode: Literal["idea_to_mv", "lyrics_to_mv"] = Field(default="idea_to_mv", description="MV制作の入力モード")
    created_at: str = Field(default_factory=now_iso)


class ProjectPaths(BaseModel):
    root: Path
    images: Path
    rag_store: Path
    design_json: Path
    image_manifest: Path

    @classmethod
    def for_project(cls, project: str, output_root: Path = Path("outputs")) -> "ProjectPaths":
        project_path = Path(project)
        if (
            not project
            or project in {".", ".."}
            or "/" in project
            or "\\" in project
            or project_path.name != project
            or project_path.is_absolute()
            or project_path.drive
        ):
            raise ValueError("プロジェクト名にはディレクトリ区切り文字や相対パスを使用できません。")
        root = output_root / project
        return cls(
            root=root,
            images=root / "images",
            rag_store=root / "rag_store.json",
            design_json=root / "design.json",
            image_manifest=root / "images" / "image_manifest.json",
        )
