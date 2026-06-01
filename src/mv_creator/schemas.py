from __future__ import annotations

from statistics import median, quantiles

from pydantic import AliasChoices, BaseModel, Field, computed_field

from mv_creator.models import (
    CharacterProfile,
    ContinuityIssue,
    ImagePrompt,
    MVVisualPlan,
    ScenePlan,
    MVBeat,
    ShotPlan,
    SongSection,
    SunoMusicParams,
    MVEditingPrompt,
)


class MVBeatList(BaseModel):
    items: list[MVBeat] = Field(default_factory=list)


class CharacterList(BaseModel):
    items: list[CharacterProfile] = Field(default_factory=list)


class SceneList(BaseModel):
    items: list[ScenePlan] = Field(default_factory=list)


class ShotList(BaseModel):
    items: list[ShotPlan] = Field(default_factory=list)


class PromptBundle(BaseModel):
    image_prompts: list[ImagePrompt] = Field(default_factory=list)
    editing_prompts: list[MVEditingPrompt] = Field(default_factory=list, validation_alias=AliasChoices("editing_prompts", "video_prompts"))


class ContinuityReport(BaseModel):
    issues: list[ContinuityIssue] = Field(default_factory=list)


class RevisionResult(BaseModel):
    notes: list[str] = Field(default_factory=list)


class SunoMusicParamsSchema(BaseModel):
    lyrics: str = Field(description="Suno向けメタタグ付き歌詞")
    style: str = Field(default="", description="SunoのStyle指定")
    estimated_duration_seconds: int = Field(default=0, ge=0, le=900, description="生成した歌詞に適した楽曲尺")
    weirdness: int = Field(default=50, ge=0, le=100, description="Weirdness (0-100)")
    style_influence: int = Field(default=80, ge=0, le=100, description="Style Influence (0-100)")
    audio_influence: int = Field(default=50, ge=0, le=100, description="Audio Influence (0-100)")


class SongSectionList(BaseModel):
    items: list[SongSection] = Field(default_factory=list)


class MVVisualPlanSchema(MVVisualPlan):
    pass


YOUTUBE_VIEW_GOAL = 1_000_000
SUBSCRIBER_GAIN_GOAL = 10_000
MIN_VIRTUAL_POST_SCENARIOS = 5


class VirtualPostScenario(BaseModel):
    scenario_name: str = Field(description="仮想投稿シナリオ名")
    assumptions: str = Field(description="露出、視聴者反応、拡散経路などの前提")
    estimated_views: int = Field(ge=0, description="この仮想投稿での推定YouTube再生数")
    estimated_comments: int = Field(ge=0, description="この仮想投稿での推定コメント数")
    estimated_subscribers_gained: int = Field(ge=0, description="この仮想投稿での推定チャンネル登録者増加数")


class ViralScore(BaseModel):
    scenarios: list[VirtualPostScenario] = Field(
        min_length=MIN_VIRTUAL_POST_SCENARIOS,
        description="異なる前提で繰り返した仮想投稿結果。最低5件",
    )
    hook_score: int = Field(ge=0, le=20, description="フックの強さ（0-20）")
    emotional_score: int = Field(ge=0, le=20, description="感情的共感（0-20）")
    trend_score: int = Field(ge=0, le=20, description="トレンド適合（0-20）")
    universality_score: int = Field(ge=0, le=15, description="歌詞の普遍性（0-15）")
    style_quality_score: int = Field(ge=0, le=15, description="Style品質（0-15）")
    retention_score: int = Field(ge=0, le=10, description="再生維持率（0-10）")
    reasoning: str = Field(description="仮想投稿結果と品質評価の根拠")

    @computed_field
    @property
    def estimated_views(self) -> int:
        return int(median(scenario.estimated_views for scenario in self.scenarios))

    @computed_field
    @property
    def estimated_comments(self) -> int:
        return int(median(scenario.estimated_comments for scenario in self.scenarios))

    @computed_field
    @property
    def estimated_subscribers_gained(self) -> int:
        return int(median(scenario.estimated_subscribers_gained for scenario in self.scenarios))

    @computed_field
    @property
    def lower_quartile_views(self) -> int:
        return _lower_quartile([scenario.estimated_views for scenario in self.scenarios])

    @computed_field
    @property
    def lower_quartile_comments(self) -> int:
        return _lower_quartile([scenario.estimated_comments for scenario in self.scenarios])

    @computed_field
    @property
    def lower_quartile_subscribers_gained(self) -> int:
        return _lower_quartile([scenario.estimated_subscribers_gained for scenario in self.scenarios])

    @computed_field
    @property
    def quality_score(self) -> int:
        return (
            self.hook_score
            + self.emotional_score
            + self.trend_score
            + self.universality_score
            + self.style_quality_score
            + self.retention_score
        )

    @computed_field
    @property
    def achieved_100(self) -> bool:
        return self.estimated_views >= YOUTUBE_VIEW_GOAL and self.estimated_subscribers_gained >= SUBSCRIBER_GAIN_GOAL

    @computed_field
    @property
    def achieved_120(self) -> bool:
        return self.lower_quartile_views >= YOUTUBE_VIEW_GOAL and self.lower_quartile_subscribers_gained >= SUBSCRIBER_GAIN_GOAL

    @computed_field
    @property
    def total_score(self) -> int:
        median_ratio = min(
            self.estimated_views / YOUTUBE_VIEW_GOAL,
            self.estimated_subscribers_gained / SUBSCRIBER_GAIN_GOAL,
        )
        lower_quartile_ratio = min(
            self.lower_quartile_views / YOUTUBE_VIEW_GOAL,
            self.lower_quartile_subscribers_gained / SUBSCRIBER_GAIN_GOAL,
        )
        if not self.achieved_100:
            return min(99, round(median_ratio * 100))
        if not self.achieved_120:
            return 100 + min(19, round(lower_quartile_ratio * 19))
        return 120 + min(30, round((lower_quartile_ratio - 1) * 30))


def _lower_quartile(values: list[int]) -> int:
    return round(quantiles(values, n=4, method="inclusive")[0])


class ViralChallenge(BaseModel):
    confirmed: bool = Field(description="スコアが妥当ならtrue、過大評価ならfalse")
    overestimated: bool = Field(description="スコアが過大評価されている場合true")
    adjusted_score: int = Field(default=0, ge=0, le=150, description="修正後のスコア（過大評価の場合）")
    correction_reason: str = Field(default="", description="修正理由")
