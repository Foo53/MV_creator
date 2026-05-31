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


class ViralScore(BaseModel):
    estimated_views: int = Field(description="推定YouTube再生数")
    estimated_comments: int = Field(description="推定コメント数")
    estimated_subscribers_gained: int = Field(description="推定チャンネル登録者増加数")
    total_score: int = Field(description="総合スコア（0-150）")
    hook_score: int = Field(description="フックの強さ（0-20）")
    emotional_score: int = Field(description="感情的共感（0-20）")
    trend_score: int = Field(description="トレンド適合（0-20）")
    universality_score: int = Field(description="歌詞の普遍性（0-15）")
    style_quality_score: int = Field(description="Style品質（0-15）")
    retention_score: int = Field(description="再生維持率（0-10）")
    reasoning: str = Field(description="スコアの根拠")


class ViralChallenge(BaseModel):
    confirmed: bool = Field(description="スコアが妥当ならtrue、過大評価ならfalse")
    overestimated: bool = Field(description="スコアが過大評価されている場合true")
    adjusted_score: int = Field(default=0, description="修正後のスコア（過大評価の場合）")
    correction_reason: str = Field(default="", description="修正理由")
