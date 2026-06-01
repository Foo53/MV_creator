from __future__ import annotations

from typing import Callable

from mv_creator.models import MVVisualPlan, ProductionBrief, ProductionDesign, SongSection, SunoMusicParams
from mv_creator.providers import LLMProvider
from mv_creator.rag import RAGStore
from mv_creator.schemas import CharacterList, ContinuityReport, MVBeatList, MVVisualPlanSchema, PromptBundle, RevisionResult, SceneList, ShotList, SongSectionList, SunoMusicParamsSchema, ViralChallenge, ViralScore


class Agent:
    name = "agent"

    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider


class IdeationAgent(Agent):
    name = "企画整理エージェント"

    def run(self, user_input: str, *, visual_style: str, music_genre: str = "", music_mood: str = "", visual_palette: str = "", release_format: str = "youtube", source_type: str = "idea") -> ProductionBrief:
        source_instruction = (
            "入力は完成済みの歌詞です。歌詞を書き直さず、歌詞の物語、感情、モチーフから静止画MVの制作ブリーフを抽出してください。"
            if source_type == "lyrics"
            else "入力はMVのアイデアです。静止画MVの制作ブリーフへ整理してください。"
        )
        creative_context = ""
        if music_genre:
            creative_context += f"\n楽曲ジャンル: {music_genre}"
        if music_mood:
            creative_context += f"\n楽曲ムード: {music_mood}"
        if visual_palette:
            creative_context += f"\nカラーパレット: {visual_palette}"
        if release_format:
            creative_context += f"\n公開フォーマット: {release_format}"
        prompt = f"""
あなたは静止画ミュージックビデオ専用の企画整理エージェントです。
ユーザーの入力を、曲作りと静止画MVの制作設計に使えるProductionBriefへ変換してください。
出力は必ず指定されたJSON Schemaに従ってください。
{still_image_mv_instruction()}
{source_instruction}

USER_INPUT: {user_input}
ビジュアルスタイル: {visual_style}
{creative_context}
"""
        brief = self.provider.generate_structured(prompt, ProductionBrief)
        brief.visual_style = brief.visual_style or visual_style
        brief.duration_seconds = 0
        brief.music_genre = music_genre or brief.music_genre
        brief.music_mood = music_mood or brief.music_mood
        brief.visual_palette = visual_palette or brief.visual_palette
        brief.release_format = release_format or brief.release_format
        return brief


class MVBeatPlannerAgent(Agent):
    name = "MVビート設計エージェント"

    def run(self, brief: ProductionBrief, mv_context: str = "") -> MVBeatList:
        prompt = f"""
あなたは静止画MVのビジュアル展開を作るエージェントです。
歌詞の感情と曲構成に沿って、3から7個のMVビートを作ってください。
各ビートは一枚絵で表現できる決定的な瞬間にしてください。
{still_image_mv_instruction()}

制作ブリーフ:
{brief.model_dump_json(indent=2)}

MV音楽・映像方針:
{mv_context or "なし"}

"""
        return self.provider.generate_structured(prompt, MVBeatList)


class CharacterAgent(Agent):
    name = "キャラクター設計エージェント"

    def run(self, brief: ProductionBrief, mv_beats: MVBeatList, rag: RAGStore, mv_context: str = "") -> CharacterList:
        context = rag.context_block(brief.logline, used_by=self.name)
        prompt = f"""
あなたはキャラクター設計エージェントです。
静止画生成で一貫性を保つため、キャラクターID、外見、服装、継続性メモを明確にしてください。
参照画像生成でそのまま使えるように、appearance、wardrobe、continuity_notes は英語で書いてください。
入力が日本語の場合も、意味を保ったまま視覚的に明確な英語へ変換してください。

RAG参照情報:
{context}

制作ブリーフ:
{brief.model_dump_json(indent=2)}

MV音楽・映像方針:
{mv_context or "なし"}

MVビート:
{mv_beats.model_dump_json(indent=2)}
"""
        result = self.provider.generate_structured(prompt, CharacterList)
        for character in result.items:
            rag.add_character(character)
        return result


class ScenePlannerAgent(Agent):
    name = "シーン設計エージェント"

    def run(self, brief: ProductionBrief, mv_beats: MVBeatList, characters: CharacterList, rag: RAGStore, mv_context: str = "") -> SceneList:
        context = rag.context_block(brief.logline, used_by=self.name)
        prompt = f"""
あなたは静止画MVのシーン設計エージェントです。
MVビートを、場所、時間、登場人物、曲中での役割、継続性要件が明確なシーンへ分割してください。

RAG参照情報:
{context}

制作ブリーフ:
{brief.model_dump_json(indent=2)}

MV音楽・映像方針:
{mv_context or "なし"}

キャラクター:
{characters.model_dump_json(indent=2)}

MVビート:
{mv_beats.model_dump_json(indent=2)}
"""
        return self.provider.generate_structured(prompt, SceneList)


class ShotDirectorAgent(Agent):
    name = "ショット設計エージェント"

    def run(self, brief: ProductionBrief, scenes: SceneList, characters: CharacterList, rag: RAGStore, mv_context: str = "") -> ShotList:
        context = rag.context_block(" ".join(scene.summary for scene in scenes.items), used_by=self.name, limit=8)
        caption_instruction = """
各ショットの lyrics_caption フィールドに、そのショットの映像に合わせた歌詞の一部（1〜2行）を入れてください。
これはミュージックビデオの歌詞字幕として使われます。歌詞は詩的で感情的な日本語にしてください。
例: 「雨の路地に光る水たまり / 小さなロボットが立ち止まる」
"""
        prompt = f"""
あなたは静止画ミュージックビデオ専用のショット設計エージェントです。
各シーンを、ChatGPT画像生成で作る一枚絵の単位へ分けてください。動画生成用の連続動作ではなく、曲の感情と物語が一目で伝わる決定的な瞬間を選んでください。
各ショットでは、照明と音に加えて次を具体化してください。
- still_image_intent: この一枚がMV全体で担う役割
- composition: 被写体の位置、前景・中景・背景、字幕を重ねるための余白
- focal_point: ゆるいパン・ズームで視線を誘導する対象と画面内の位置
- still_duration_seconds: 曲構成に合わせた表示尺。全ショットの合計は制作ブリーフの想定尺に近づける
- transition_type: 基本はcrossfade。強いビートや場面転換だけcut
- transition_duration_seconds: crossfadeは0.4〜1.0秒程度、cutは0秒
motion は slow zoom in, slow zoom out, slow pan left, slow pan right, slow pan up, slow pan down, hold を中心にしてください。
motion_start と motion_end は、静止画に加える穏やかなパン・ズームの開始構図と終了構図として書いてください。
music_sync_notes には、対応する楽曲セクション、ビート、歌詞の感情との同期方針を書いてください。
RAG参照情報に含まれるキャラクターや世界観の一貫性を必ず守ってください。
{still_image_mv_instruction()}
{caption_instruction}

RAG参照情報:
{context}

制作ブリーフ:
{brief.model_dump_json(indent=2)}

MV音楽・映像方針:
{mv_context or "なし"}

キャラクター:
{characters.model_dump_json(indent=2)}

シーン:
{scenes.model_dump_json(indent=2)}
"""
        result = self.provider.generate_structured(prompt, ShotList)
        for shot in result.items:
            rag.add_shot(shot)
        return result


class PromptEngineerAgent(Agent):
    name = "プロンプト設計エージェント"

    def run(self, brief: ProductionBrief, shots: ShotList, rag: RAGStore, mv_context: str = "") -> PromptBundle:
        context = rag.context_block(" ".join(shot.description for shot in shots.items), used_by=self.name, limit=10)
        prompt = f"""
あなたは静止画ミュージックビデオ専用のプロンプト設計エージェントです。
ショット設計から、ChatGPT画像生成へ貼り付ける画像プロンプトと、Remotionで静止画MVを組み立てるための editing_prompts を作成してください。
画像プロンプトは、一枚絵として成立する決定的な瞬間を具体化してください。被写体、構図、前景・中景・背景、照明、色、焦点、字幕用の余白、画像全体の統一感を明記してください。
連続動作、動画生成、複数カット、分割画面、絵コンテ、コラージュを要求しないでください。画像内に文字、字幕、ロゴ、透かしを描かせないでください。
editing_prompts は、Remotionで行うパン・ズーム、ホールド、クロスフェード、字幕表示、楽曲同期の編集指示です。
画像生成モデルでの安定性を高めるため、image_prompts.prompt と image_prompts.negative_prompt は英語で書いてください。
入力情報が日本語の場合も、意味を保ったまま英語の画像生成プロンプトに変換してください。
{still_image_mv_instruction()}

RAG参照情報:
{context}

制作ブリーフ:
{brief.model_dump_json(indent=2)}

MV音楽・映像方針:
{mv_context or "なし"}

ショット:
{shots.model_dump_json(indent=2)}
"""
        result = self.provider.generate_structured(prompt, PromptBundle)
        for image_prompt in result.image_prompts:
            rag.add_prompt(image_prompt)
        return result


class ContinuityCriticAgent(Agent):
    name = "継続性評価エージェント"

    def run(self, design: ProductionDesign, rag: RAGStore) -> ContinuityReport:
        context = rag.context_block(design.brief.logline, used_by=self.name, limit=12)
        prompt = f"""
あなたは継続性評価エージェントです。
キャラクターの外見、衣装、時系列、場所、画面連続性、プロンプトの弱さを確認してください。
問題がある場合だけ、具体的で修正可能な指摘を返してください。

RAG参照情報:
{context}

制作設計:
{design.model_dump_json(indent=2)}
"""
        return self.provider.generate_structured(prompt, ContinuityReport)


class RevisionAgent(Agent):
    name = "修正エージェント"

    def run(self, design: ProductionDesign, rag: RAGStore) -> RevisionResult:
        prompt = f"""
あなたは修正エージェントです。
継続性評価の指摘を読み、制作設計を改善するための短い修正方針を返してください。
完全な設計書を書き直すのではなく、どこをどう直すべきかを簡潔に返してください。

制作設計:
{design.model_dump_json(indent=2)}
"""
        return self.provider.generate_structured(prompt, RevisionResult)


class MusicAgent(Agent):
    name = "音楽設計エージェント"

    def run(self, brief: ProductionBrief, *, message: str = "") -> SunoMusicParams:
        genre_context = ""
        if brief.music_genre:
            genre_context += f"\n楽曲ジャンル: {brief.music_genre}"
        if brief.music_mood:
            genre_context += f"\n楽曲ムード: {brief.music_mood}"
        regeneration = ""
        if message:
            regeneration = f"\n追加の要望: {message}\nこの要望を反映してパラメータを再生成してください。"
        prompt = f"""
あなたは音楽設計エージェントです。
MVのアイデアから、Suno AIで楽曲を生成するためのパラメータを作成してください。

タイトル: {brief.title}
ログライン: {brief.logline}
ビジュアルスタイル: {brief.visual_style}
{genre_context}
{regeneration}

以下の形式で出力してください:

- lyrics: Suno向けのメタタグ付き歌詞。以下のルールに従ってください:
  - セクションタグ: [Intro], [Verse 1], [Pre-Chorus], [Chorus], [Post-Chorus], [Bridge], [Outro], [End] を適切に使い分けて構造化する。
  - コロン構文で演出を指定: [Verse 1: soft vocals, piano], [Chorus: powerful vocals, full band] のようにセクションタグに続けてボーカルや楽器の指定を記述する。
  - ボーカルタグ: [Male Vocal], [Female Vocal], [Whisper], [Harmonies] 等を適宜使用。
  - インストゥルメンタルタグ: [Piano], [Synth], [Acoustic Guitar], [Strings] 等を適宜使用。
  - 改行ルール: 改行は「息継ぎ」を意味する。セクション間は空行で区切る。
  - 最後に [End] タグを置き、曲の終了を明示する（トレイル音防止）。
  - 歌詞は日本語で、映像の世界観に合う詩的な内容にする。
  - 曲として自然に完結する長さを選び、概ね1行あたり3秒とセクションごとの間奏を考慮する。

- style: Sunoが理解できる英語のStyle指定。以下のフォーマットで4-7個の記述子をカンマ区切りで記述（120文字以内）:
  [Genre], [Tempo/Energy], [Key Instruments], [Vocal Style], [Production Quality], [Mood]
  例: "cinematic electronic, mid-tempo, synth and piano, soft female vocals, polished, melancholic"
  例: "J-Pop, upbeat, electric guitar and synth, bright female vocals, polished, cheerful"

- weirdness: 創造性の度合い 0-100（50=標準、低いほど保守的、高いほど実験的）
- style_influence: Style指定への忠実度 0-100（高いほどStyleに厳密に従う）
- audio_influence: 音響的探求度 0-100（音声アップロードがない場合は50固定でよい）
- estimated_duration_seconds: 生成した歌詞と曲構成に適した楽曲尺。秒単位で指定する
"""
        result = self.provider.generate_structured(prompt, SunoMusicParamsSchema)
        return SunoMusicParams(
            lyrics=result.lyrics,
            style=result.style,
            estimated_duration_seconds=result.estimated_duration_seconds,
            weirdness=result.weirdness,
            style_influence=result.style_influence,
            audio_influence=result.audio_influence,
        )


class LyricImproverAgent(Agent):
    name = "歌詞改善エージェント"

    def __init__(self, provider: LLMProvider) -> None:
        super().__init__(provider)
        self._context = ""
        self.last_target_achieved = False
        self.last_score: ViralScore | None = None

    def run(self, brief: ProductionBrief, suno_params: SunoMusicParams, *, progress_callback: Callable[[str, int, int], None] | None = None) -> SunoMusicParamsSchema:
        self._context = f"タイトル: {brief.title}\nログライン: {brief.logline}\nビジュアルスタイル: {brief.visual_style}\n想定尺: {brief.duration_seconds}秒"
        self.last_target_achieved = False
        self.last_score = None
        current = suno_params.model_copy(deep=True)
        best = current.model_copy(deep=True)
        best_score = -1
        best_evaluation: ViralScore | None = None
        max_iterations = 10
        target_score = 100

        for iteration in range(1, max_iterations + 1):
            if progress_callback:
                phase = "100点目標" if target_score == 100 else "120点目標"
                progress_callback(f"{phase}: {iteration}回目の評価中（現在{target_score}点未満）", iteration, max_iterations)

            score = self._evaluate(current)
            challenge: ViralChallenge | None = None
            effective_score = score.total_score

            if progress_callback:
                phase = "100点目標" if target_score == 100 else "120点目標"
                progress_callback(
                    f"{phase}: {iteration}回目 → {score.total_score}点 "
                    f"（中央値: {score.estimated_views:,}再生 / 登録者+{score.estimated_subscribers_gained:,}、"
                    f"下位25%: {score.lower_quartile_views:,}再生 / 登録者+{score.lower_quartile_subscribers_gained:,}）",
                    iteration,
                    max_iterations,
                )

            if self._meets_target(score, target_score):
                challenge = self._challenge(current, score, target_score)
                if challenge.overestimated or not challenge.confirmed:
                    effective_score = challenge.adjusted_score or min(score.total_score, target_score - 1)

            if effective_score > best_score:
                best = current.model_copy(deep=True)
                best_score = effective_score
                best_evaluation = score

            if challenge is not None:
                if challenge.confirmed and not challenge.overestimated:
                    if target_score == 100:
                        if progress_callback:
                            progress_callback(f"100点達成・検証OK → 120点目標へ移行", iteration, max_iterations)
                        target_score = 120
                        continue
                    else:
                        if progress_callback:
                            progress_callback(f"120点達成・検証OK → 最終出力", iteration, max_iterations)
                        self.last_target_achieved = True
                        self.last_score = score
                        return self._to_schema(current)
                else:
                    if progress_callback:
                        progress_callback(f"検証結果: 過大評価（修正後{effective_score}点）→ 改善継続", iteration, max_iterations)

            current = self._improve(current, score, target_score, challenge=challenge)

        if progress_callback:
            progress_callback(f"目標未達: 最大イテレーション到達 → 最良結果を出力", max_iterations, max_iterations)
        self.last_score = best_evaluation
        return self._to_schema(best)

    @staticmethod
    def _meets_target(score: ViralScore, target_score: int) -> bool:
        return score.achieved_100 if target_score == 100 else score.achieved_120

    def _evaluate(self, suno_params: SunoMusicParams) -> ViralScore:
        prompt = f"""
あなたはYouTube音楽動画のバイラル_potential（拡散可能性）を評価する専門家です。
以下のSunoパラメータをYouTubeへ投稿したと仮定し、異なる前提で最低5回の仮想投稿を実行してください。
各シナリオで、再生数、コメント数、登録者増加数の仮説と、その前提を提示してください。

{self._context}

評価対象のSunoパラメータ:
{suno_params.model_dump_json(indent=2)}

品質評価（合計100点満点）:
- hook_score: フックの強さ（0-20点）サビやメロディが記憶に残り、一度聞いたら頭から離れないか
- emotional_score: 感情的共感（0-20点）リスナーが自分の体験と重ねられる普遍的な感情があるか
- trend_score: トレンド適合（0-20点）YouTubeやSNSで現在拡散されている音楽ジャンル・雰囲気に合致するか
- universality_score: 歌詞の普遍性（0-15点）幅広い年齢・国籍の層に響く表現か
- style_quality_score: Style品質（0-15点）SunoのStyle指定が音質とジャンル再現性を最大化しているか
- retention_score: 再生維持率（0-10点）Intro→Verse→Chorusの展開が最後まで聞きたくなる構成か

判定ロジックはサーバー側で適用します:
- 100点到達: 仮想投稿の中央値で100万再生以上、かつ登録者増加1万件以上
- 120点到達: 下位25%の仮想投稿でも100万再生以上、かつ登録者増加1万件以上
- コメント数はエンゲージメントの仮説として提示するが、到達条件には直接使わない
"""
        return self.provider.generate_structured(prompt, ViralScore)

    def _challenge(self, suno_params: SunoMusicParams, score: ViralScore, target_score: int) -> ViralChallenge:
        prompt = f"""
あなたは厳格な審査員です。以下の楽曲が{target_score}点に達したという評価が妥当か検証してください。
自己評価は甘くなりがちです。本当に{target_score}点に値するか、厳しく判定してください。

{self._context}

評価されたSunoパラメータ:
{suno_params.model_dump_json(indent=2)}

現在の達成度: {score.total_score}点
品質評価: {score.quality_score}点
内訳: フック{score.hook_score} 共感{score.emotional_score} トレンド{score.trend_score} 普遍性{score.universality_score} Style品質{score.style_quality_score} 再生維持{score.retention_score}
中央値: 再生数{score.estimated_views} / コメント数{score.estimated_comments} / 登録者増加{score.estimated_subscribers_gained}
下位25%値: 再生数{score.lower_quartile_views} / コメント数{score.lower_quartile_comments} / 登録者増加{score.lower_quartile_subscribers_gained}
仮想投稿結果:
{[scenario.model_dump() for scenario in score.scenarios]}

100点は中央値で100万再生・1万登録者増加、120点は下位25%値でも同条件を満たす状態です。今回の目標は{target_score}点です。
本当にこの楽曲がそのレベルに達しているか、以下の観点から判定してください:
- 同じジャンルの実際のYouTubeヒット曲と比較して遜色ないか
- 歌詞に「人にシェアしたくなる」要素が十分あるか
- Style指定がSunoで高品質な出力を生む設定になっているか
"""
        return self.provider.generate_structured(prompt, ViralChallenge)

    def _improve(self, current: SunoMusicParams, score: ViralScore, target_score: int, *, challenge: ViralChallenge | None = None) -> SunoMusicParams:
        effective_score = score.total_score
        challenge_feedback = ""
        if challenge is not None and (challenge.overestimated or not challenge.confirmed):
            effective_score = challenge.adjusted_score or min(score.total_score, target_score - 1)
            challenge_feedback = f"""
厳格な審査員による修正:
- 修正後スコア: {effective_score}
- 修正理由: {challenge.correction_reason or "目標品質への到達根拠が不足しています。"}
この指摘を必ず改善に反映してください。
"""
        prompt = f"""
あなたはYouTubeでバズる楽曲を設計する専門家です。
現在のスコア{effective_score}点を目標{target_score}点に引き上げるため、Sunoパラメータを改善してください。

{self._context}
{challenge_feedback}

現在のSunoパラメータ:
{current.model_dump_json(indent=2)}

仮想投稿の集計:
- 達成度: {score.total_score}/150
- 品質評価: {score.quality_score}/100
- 中央値: {score.estimated_views}再生 / コメント{score.estimated_comments}件 / 登録者+{score.estimated_subscribers_gained}
- 下位25%値: {score.lower_quartile_views}再生 / コメント{score.lower_quartile_comments}件 / 登録者+{score.lower_quartile_subscribers_gained}

現在のスコア内訳:
- フックの強さ: {score.hook_score}/20
- 感情的共感: {score.emotional_score}/20
- トレンド適合: {score.trend_score}/20
- 歌詞の普遍性: {score.universality_score}/15
- Style品質: {score.style_quality_score}/15
- 再生維持率: {score.retention_score}/10

低いスコアの基準を中心に改善してください。
改善のポイント:
- フックが弱い → サビのメロディや歌詞を印象的にするセクションタグを活用
- 共感が低い → リスナーが自分を重ねられる普遍的な感情表現を追加
- トレンド適合 → YouTubeで伸びているジャンルの要素を取り入れる
- 普遍性 → 年齢や背景を問わず響く表現にする
- Style品質 → Sunoが高品質に生成できる記述子に調整
- 再生維持 → Introで惹きつけ、各セクションで展開を作る
"""
        result = self.provider.generate_structured(prompt, SunoMusicParamsSchema)
        return SunoMusicParams(
            lyrics=result.lyrics,
            style=result.style,
            estimated_duration_seconds=result.estimated_duration_seconds,
            weirdness=result.weirdness,
            style_influence=result.style_influence,
            audio_influence=result.audio_influence,
            audio_path=current.audio_path,
        )

    def _to_schema(self, suno_params: SunoMusicParams) -> SunoMusicParamsSchema:
        return SunoMusicParamsSchema(
            lyrics=suno_params.lyrics,
            style=suno_params.style,
            estimated_duration_seconds=suno_params.estimated_duration_seconds,
            weirdness=suno_params.weirdness,
            style_influence=suno_params.style_influence,
            audio_influence=suno_params.audio_influence,
        )


class SongAnalysisAgent(Agent):
    name = "楽曲構成分析エージェント"

    def run(self, brief: ProductionBrief, suno_params: SunoMusicParams) -> list[SongSection]:
        prompt = f"""
あなたはMV制作のための楽曲構成分析エージェントです。
Suno用の歌詞とstyleを読み、映像設計に使えるように曲をセクションへ分解してください。
各セクションには、section_id、label、lyrics、mood、visual_intent、estimated_duration_seconds を入れてください。
歌詞内の [Intro] [Verse] [Chorus] [Bridge] [Outro] [End] などのタグを尊重してください。
既存の想定尺へ合わせるのではなく、歌詞量、style、セクション構成から自然な秒数を見積もってください。

制作ブリーフ:
{brief.model_dump_json(indent=2)}

Sunoパラメータ:
{suno_params.model_dump_json(indent=2)}
"""
        return self.provider.generate_structured(prompt, SongSectionList).items


class MVVisualPlannerAgent(Agent):
    name = "MV映像方針エージェント"

    def run(self, brief: ProductionBrief, suno_params: SunoMusicParams, song_sections: list[SongSection]) -> MVVisualPlan:
        prompt = f"""
あなたはミュージックビデオの映像方針を作るエージェントです。
入力されたSuno歌詞、style、曲構成に基づき、以降のMVビート・キャラクター・シーン・ショット・画像プロンプト生成が曲に準拠できる映像方針を作ってください。
単なるアイデア映像ではなく、曲のセクション、歌詞の感情、styleの音楽ジャンル・テンポ・楽器感に映像が同期するようにしてください。

制作ブリーフ:
{brief.model_dump_json(indent=2)}

Sunoパラメータ:
{suno_params.model_dump_json(indent=2)}

曲構成:
{[section.model_dump() for section in song_sections]}
"""
        return self.provider.generate_structured(prompt, MVVisualPlanSchema)


def build_mv_context(
    *,
    suno_params: SunoMusicParams | None,
    song_sections: list[SongSection] | None = None,
    mv_visual_plan: MVVisualPlan | None = None,
) -> str:
    if not suno_params:
        return ""
    parts = [
        "この制作はMVモードです。以降の映像設計は、入力アイデアだけでなく、生成済みまたは編集済みのSuno歌詞・style・曲構成に準拠してください。",
        "Sunoパラメータ:",
        suno_params.model_dump_json(indent=2),
    ]
    if song_sections:
        parts.extend(["曲構成:", "\n".join(section.model_dump_json() for section in song_sections)])
    if mv_visual_plan:
        parts.extend(["MV映像方針:", mv_visual_plan.model_dump_json(indent=2)])
    return "\n".join(parts)


def still_image_mv_instruction() -> str:
    return """
静止画MV制作方針:
Sunoで生成した音楽に合わせて、ChatGPTで生成した一枚絵をRemotionでつなぎ、歌詞字幕を重ねる静止画ミュージックビデオを制作します。
- ショットは楽曲の各セクション（Intro, Verse, Chorus, Bridge, Outro）に対応するように設計してください。
- 各ショットは単独の1枚絵として成立させてください。複数カット、分割画面、連続動作を1枚に詰め込まないでください。
- 被写体の注視点、前景・中景・背景、字幕を置く余白を設計し、ゆるいズームやパンで楽曲のテンポ感に合わせてください。
- motion は楽曲の雰囲気に合うよう slow zoom, slow pan, hold を中心にしてください。
- music_sync_notes には楽曲のセクション名と雰囲気を含めてください（例: 「Verse 1: 静かで神秘的な電子音」）。
- editing_prompts はRemotionでの静止画MV編集指示として、楽曲との同期を意識した内容にしてください。
- image_prompts は楽曲の感情やビジュアルテーマを反映した構図にしてください。
"""
