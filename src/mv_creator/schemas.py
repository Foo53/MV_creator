from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

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
    estimated_views: int = Field(ge=0, description="推定YouTube再生数")
    estimated_comments: int = Field(ge=0, description="推定コメント数")
    estimated_subscribers_gained: int = Field(ge=0, description="推定チャンネル登録者増加数")
    total_score: int = Field(description="総合スコア（基礎点とバイラル加点の合計、0-150。サーバー側で再計算）")
    hook_score: int = Field(ge=0, le=20, description="フックの強さ（0-20）")
    emotional_score: int = Field(ge=0, le=20, description="感情的共感（0-20）")
    trend_score: int = Field(ge=0, le=20, description="トレンド適合（0-20）")
    universality_score: int = Field(ge=0, le=15, description="歌詞の普遍性（0-15）")
    style_quality_score: int = Field(ge=0, le=15, description="Style品質（0-15）")
    retention_score: int = Field(ge=0, le=10, description="再生維持率（0-10）")
    viral_bonus_score: int = Field(default=0, ge=0, le=50, description="突出した拡散性に対する加点（0-50）")
    reasoning: str = Field(description="スコアの根拠")

    @model_validator(mode="after")
    def validate_total_score(self) -> "ViralScore":
        expected = (
            self.hook_score
            + self.emotional_score
            + self.trend_score
            + self.universality_score
            + self.style_quality_score
            + self.retention_score
            + self.viral_bonus_score
        )
        self.total_score = expected
        return self


class ViralChallenge(BaseModel):
    confirmed: bool = Field(description="スコアが妥当ならtrue、過大評価ならfalse")
    overestimated: bool = Field(description="スコアが過大評価されている場合true")
    adjusted_score: int = Field(default=0, ge=0, le=150, description="修正後のスコア（過大評価の場合）")
    correction_reason: str = Field(default="", description="修正理由")
