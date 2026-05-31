from __future__ import annotations

from mv_creator.models import MVVisualPlan, ProductionBrief, ProductionDesign, SongSection, SunoMusicParams
from mv_creator.providers import LLMProvider
from mv_creator.rag import RAGStore
from mv_creator.schemas import CharacterList, ContinuityReport, MVVisualPlanSchema, PromptBundle, RevisionResult, SceneList, ScriptList, ShotList, SongSectionList, SunoMusicParamsSchema


class Agent:
    name = "agent"

    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider


class IdeationAgent(Agent):
    name = "企画整理エージェント"

    def run(self, user_input: str, *, audience: str, style: str, duration_seconds: int, output_mode: str = "mv", genre: str = "", mood: str = "", color_tone: str = "", narration_style: str = "", target_platform: str = "") -> ProductionBrief:
        mode_instruction = output_mode_instruction(output_mode)
        creative_context = ""
        if genre:
            creative_context += f"\nジャンル: {genre}"
        if mood:
            creative_context += f"\n雰囲気: {mood}"
        if color_tone:
            creative_context += f"\n色調: {color_tone}"
        if narration_style:
            creative_context += f"\nナレーション文体: {narration_style}"
        if target_platform:
            creative_context += f"\n配信プラットフォーム: {target_platform}"
        prompt = f"""
あなたはViMax風の動画制作ワークフローにおける企画整理エージェントです。
ユーザーの入力を、短編映像の制作設計に使えるProductionBriefへ変換してください。
出力は必ず指定されたJSON Schemaに従ってください。
{mode_instruction}

USER_INPUT: {user_input}
想定視聴者: {audience}
映像スタイル: {style}
想定尺: {duration_seconds}秒
OUTPUT_MODE: {output_mode}
{creative_context}
"""
        brief = self.provider.generate_structured(prompt, ProductionBrief)
        brief.audience = brief.audience or audience
        brief.style = brief.style or style
        brief.duration_seconds = duration_seconds
        brief.output_mode = output_mode if output_mode in {"mv"} else "mv"
        return brief


class ScreenwriterAgent(Agent):
    name = "脚本エージェント"

    def run(self, brief: ProductionBrief, source_script: str | None = None, mv_context: str = "") -> ScriptList:
        mode_instruction = output_mode_instruction(brief.output_mode)
        prompt = f"""
あなたは脚本エージェントです。
短編映像向けに3から7個のビートを作ってください。
既存脚本がある場合は、主要な出来事を保ちながら映像向けに整理してください。
{mode_instruction}

制作ブリーフ:
{brief.model_dump_json(indent=2)}

MV音楽・映像方針:
{mv_context or "なし"}

既存脚本:
{source_script or "なし"}
"""
        return self.provider.generate_structured(prompt, ScriptList)


class CharacterAgent(Agent):
    name = "キャラクター設計エージェント"

    def run(self, brief: ProductionBrief, script: ScriptList, rag: RAGStore, mv_context: str = "") -> CharacterList:
        context = rag.context_block(brief.logline, used_by=self.name)
        prompt = f"""
あなたはキャラクター設計エージェントです。
映像生成で一貫性を保つため、キャラクターID、外見、服装、声、継続性メモを明確にしてください。
参照画像生成でそのまま使えるように、appearance、wardrobe、continuity_notes は英語で書いてください。
入力が日本語の場合も、意味を保ったまま視覚的に明確な英語へ変換してください。

RAG参照情報:
{context}

制作ブリーフ:
{brief.model_dump_json(indent=2)}

MV音楽・映像方針:
{mv_context or "なし"}

脚本ビート:
{script.model_dump_json(indent=2)}
"""
        result = self.provider.generate_structured(prompt, CharacterList)
        for character in result.items:
            rag.add_character(character)
        return result


class ScenePlannerAgent(Agent):
    name = "シーン設計エージェント"

    def run(self, brief: ProductionBrief, script: ScriptList, characters: CharacterList, rag: RAGStore, mv_context: str = "") -> SceneList:
        context = rag.context_block(brief.logline, used_by=self.name)
        prompt = f"""
あなたはシーン設計エージェントです。
脚本ビートを、場所、時間、登場人物、目的、継続性要件が明確なシーンへ分割してください。

RAG参照情報:
{context}

制作ブリーフ:
{brief.model_dump_json(indent=2)}

MV音楽・映像方針:
{mv_context or "なし"}

キャラクター:
{characters.model_dump_json(indent=2)}

脚本ビート:
{script.model_dump_json(indent=2)}
"""
        return self.provider.generate_structured(prompt, SceneList)


class ShotDirectorAgent(Agent):
    name = "ショット設計エージェント"

    def run(self, brief: ProductionBrief, scenes: SceneList, characters: CharacterList, rag: RAGStore, mv_context: str = "") -> ShotList:
        context = rag.context_block(" ".join(scene.summary for scene in scenes.items), used_by=self.name, limit=8)
        mode_instruction = output_mode_instruction(brief.output_mode)
        caption_instruction = """
各ショットの narration_caption フィールドに、そのショットの映像に合わせた歌詞の一部（1〜2行）を入れてください。
これはミュージックビデオの歌詞字幕として使われます。歌詞は詩的で感情的な日本語にしてください。
例: 「雨の路地に光る水たまり / 小さなロボットが立ち止まる」
"""
        prompt = f"""
あなたはショット設計エージェントです。
各シーンをショット単位に分け、カメラ、レンズ、動き、first frame、last frame、照明、音を具体化してください。
RAG参照情報に含まれるキャラクターや世界観の一貫性を必ず守ってください。
{mode_instruction}
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
        mode_instruction = output_mode_instruction(brief.output_mode)
        prompt = f"""
あなたはプロンプト設計エージェントです。
ショット設計から、画像生成プロンプトと動画生成プロンプトを作成してください。
画像プロンプトは視覚要素を具体的に、動画プロンプトは時間変化とカメラ移動を具体的に書いてください。
画像生成モデルでの安定性を高めるため、image_prompts.prompt と image_prompts.negative_prompt は英語で書いてください。
入力情報が日本語の場合も、意味を保ったまま英語の画像生成プロンプトに変換してください。
{mode_instruction}

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
        if brief.genre:
            genre_context += f"\nジャンル: {brief.genre}"
        if brief.mood:
            genre_context += f"\n雰囲気: {brief.mood}"
        if brief.color_tone:
            genre_context += f"\n色調: {brief.color_tone}"
        regeneration = ""
        if message:
            regeneration = f"\n追加の要望: {message}\nこの要望を反映してパラメータを再生成してください。"
        prompt = f"""
あなたは音楽設計エージェントです。
映像作品のアイデアから、Suno AIで音楽を生成するためのパラメータを作成してください。

タイトル: {brief.title}
ログライン: {brief.logline}
映像スタイル: {brief.style}
想定尺: {brief.duration_seconds}秒
{genre_context}
{regeneration}

以下の形式で出力してください:

- lyrics: Suno向けのメタタグ付き歌詞。以下のルールに従ってください:
  - セクションタグ: [Intro], [Verse 1], [Pre-Chorus], [Chorus], [Post-Chorus], [Bridge], [Outro], [End] を適切に使い分けて構造化する。短い尺（60秒以下）では [Pre-Chorus], [Post-Chorus] は省略してよい。
  - コロン構文で演出を指定: [Verse 1: soft vocals, piano], [Chorus: powerful vocals, full band] のようにセクションタグに続けてボーカルや楽器の指定を記述する。
  - ボーカルタグ: [Male Vocal], [Female Vocal], [Whisper], [Harmonies] 等を適宜使用。
  - インストゥルメンタルタグ: [Piano], [Synth], [Acoustic Guitar], [Strings] 等を適宜使用。
  - 改行ルール: 改行は「息継ぎ」を意味する。セクション間は空行で区切る。
  - 最後に [End] タグを置き、曲の終了を明示する（トレイル音防止）。
  - 歌詞は日本語で、映像の世界観に合う詩的な内容にする。
  - 想定尺{brief.duration_seconds}秒に収まる長さにする（概ね1行あたり3秒で計算）。

- style: Sunoが理解できる英語のStyle指定。以下のフォーマットで4-7個の記述子をカンマ区切りで記述（120文字以内）:
  [Genre], [Tempo/Energy], [Key Instruments], [Vocal Style], [Production Quality], [Mood]
  例: "cinematic electronic, mid-tempo, synth and piano, soft female vocals, polished, melancholic"
  例: "J-Pop, upbeat, electric guitar and synth, bright female vocals, polished, cheerful"

- weirdness: 創造性の度合い 0-100（50=標準、低いほど保守的、高いほど実験的）
- style_influence: Style指定への忠実度 0-100（高いほどStyleに厳密に従う）
- audio_influence: 音響的探求度 0-100（音声アップロードがない場合は50固定でよい）
"""
        result = self.provider.generate_structured(prompt, SunoMusicParamsSchema)
        return SunoMusicParams(
            lyrics=result.lyrics,
            style=result.style,
            weirdness=result.weirdness,
            style_influence=result.style_influence,
            audio_influence=result.audio_influence,
        )


class SongAnalysisAgent(Agent):
    name = "楽曲構成分析エージェント"

    def run(self, brief: ProductionBrief, suno_params: SunoMusicParams) -> list[SongSection]:
        prompt = f"""
あなたはMV制作のための楽曲構成分析エージェントです。
Suno用の歌詞とstyleを読み、映像設計に使えるように曲をセクションへ分解してください。
各セクションには、section_id、label、lyrics、mood、visual_intent、estimated_duration_seconds を入れてください。
歌詞内の [Intro] [Verse] [Chorus] [Bridge] [Outro] [End] などのタグを尊重してください。

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
入力されたSuno歌詞、style、曲構成に基づき、以降の脚本・キャラクター・シーン・ショット・画像プロンプト生成が曲に準拠できる映像方針を作ってください。
単なるアイデア映像ではなく、曲のセクション、歌詞の感情、styleの音楽ジャンル・テンポ・楽器感に映像が同期するようにしてください。

制作ブリーフ:
{brief.model_dump_json(indent=2)}

Sunoパラメータ:
{suno_params.model_dump_json(indent=2)}

曲構成:
{[section.model_dump() for section in song_sections]}
"""
        return self.provider.generate_structured(prompt, MVVisualPlanSchema)


def _narration_style_guide(narration_style: str) -> str:
    guides = {
        "third_person": "三人称の語り口で、情景と出来事を物語のように書いてください。",
        "first_person": "主人公の一人称で、その場の気持ちや気づきを語るように書いてください。",
        "dialogue": "キャラクターのセリフや掛け合いの形式で書いてください。",
        "none": "",
    }
    return guides.get(narration_style, "絵本のように、やさしい語り口で情景と感情を伝える短い文にしてください。")


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


def output_mode_instruction(output_mode: str) -> str:
    return """
出力モード: Music Video (MV) mode.
このモードではSunoで生成した音楽に合わせて、静止画をRemotionでつなぎ、歌詞字幕を重ねるミュージックビデオを制作します。
- ショットは楽曲の各セクション（Intro, Verse, Chorus, Bridge, Outro）に対応するように設計してください。
- 各ショットは1枚絵として成立し、ゆるいズームやパンで楽曲のテンポ感に合わせてください。
- motion は楽曲の雰囲気に合うよう slow zoom, slow pan, hold を中心にしてください。
- audio には楽曲のセクション名と雰囲気を含めてください（例: 「Verse 1: 静かで神秘的な電子音」）。
- video_prompts はRemotionでの編集指示として、楽曲との同期を意識した内容にしてください。
- image_prompts は楽曲の感情やビジュアルテーマを反映した構図にしてください。
"""
