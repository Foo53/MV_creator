from __future__ import annotations

from pydantic import BaseModel, Field

from mv_creator.models import (
    CharacterProfile,
    ContinuityIssue,
    ImagePrompt,
    MVVisualPlan,
    ScenePlan,
    ScriptBeat,
    ShotPlan,
    SongSection,
    SunoMusicParams,
    VideoPrompt,
)


class ScriptList(BaseModel):
    items: list[ScriptBeat] = Field(default_factory=list)


class CharacterList(BaseModel):
    items: list[CharacterProfile] = Field(default_factory=list)


class SceneList(BaseModel):
    items: list[ScenePlan] = Field(default_factory=list)


class ShotList(BaseModel):
    items: list[ShotPlan] = Field(default_factory=list)


class PromptBundle(BaseModel):
    image_prompts: list[ImagePrompt] = Field(default_factory=list)
    video_prompts: list[VideoPrompt] = Field(default_factory=list)


class ContinuityReport(BaseModel):
    issues: list[ContinuityIssue] = Field(default_factory=list)


class RevisionResult(BaseModel):
    notes: list[str] = Field(default_factory=list)


class SunoMusicParamsSchema(BaseModel):
    lyrics: str = Field(description="Suno向けメタタグ付き歌詞")
    style: str = Field(default="", description="SunoのStyle指定")
    weirdness: int = Field(default=50, ge=0, le=100, description="Weirdness (0-100)")
    style_influence: int = Field(default=80, ge=0, le=100, description="Style Influence (0-100)")
    audio_influence: int = Field(default=50, ge=0, le=100, description="Audio Influence (0-100)")


class SongSectionList(BaseModel):
    items: list[SongSection] = Field(default_factory=list)


class MVVisualPlanSchema(MVVisualPlan):
    pass
