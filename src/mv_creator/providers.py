from __future__ import annotations

import json
import os
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ProviderError(RuntimeError):
    pass


class LLMProvider(ABC):
    @abstractmethod
    def generate_structured(self, prompt: str, schema_model: type[T]) -> T:
        raise NotImplementedError


class GeminiProvider(LLMProvider):
    def __init__(
        self,
        model: str = "gemini-2.5-flash",
        api_key: str | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ProviderError("provider=gemini では GEMINI_API_KEY が必要です。")
        try:
            from google import genai
        except Exception as exc:  # pragma: no cover
            raise ProviderError("google-genai が見つかりません。pip install -e . を実行してください。") from exc
        self._genai = genai
        self.client = genai.Client(api_key=self.api_key)

    def generate_structured(self, prompt: str, schema_model: type[T]) -> T:
        from google.genai import types

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema_model,
                ),
            )
        except Exception as exc:
            raise _friendly_gemini_error(exc, self.model) from exc
        if not getattr(response, "text", None):
            raise ProviderError("Gemini から構造化テキストが返りませんでした。")
        return schema_model.model_validate_json(response.text)


class ClaudeProvider(LLMProvider):
    """`claude -p`を使ってテキスト生成を行うProvider。"""

    def generate_structured(self, prompt: str, schema_model: type[T]) -> T:
        schema_json = schema_model.model_json_schema()
        full_prompt = (
            f"{prompt}\n\n"
            "必ず次のJSON Schemaに従ったJSONだけを返してください。"
            "JSON以外の説明文は一切含めないでください。\n"
            f"```json-schema\n{json.dumps(schema_json, ensure_ascii=False, indent=2)}\n```"
        )
        try:
            result = subprocess.run(
                ["claude", "-p", full_prompt],
                capture_output=True,
                text=True,
                timeout=300,
            )
        except FileNotFoundError:
            raise ProviderError("claude コマンドが見つかりません。Claude Code CLIをインストールしてください。")
        except subprocess.TimeoutExpired:
            raise ProviderError("claude -p がタイムアウトしました。")
        if result.returncode != 0:
            raise ProviderError(f"claude -p がエラーを返しました: {result.stderr.strip()}")
        text = result.stdout.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [line for line in lines if not line.strip().startswith("```")]
            text = "\n".join(lines).strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            raise ProviderError(f"claude -p の応答をJSONとしてパースできませんでした: {text[:300]}")
        return schema_model.model_validate(data)


class MockProvider(LLMProvider):
    """API課金なしで学習・テストするための決定的なProvider。"""

    def generate_structured(self, prompt: str, schema_model: type[T]) -> T:
        data = _mock_payload(schema_model.__name__, prompt)
        return schema_model.model_validate(data)


def make_provider(kind: str, model: str) -> LLMProvider:
    if kind == "gemini":
        return GeminiProvider(model=model)
    if kind == "claude":
        return ClaudeProvider()
    if kind == "mock":
        return MockProvider()
    raise ProviderError(f"未知のProviderです: {kind}")


def _friendly_gemini_error(exc: Exception, model: str) -> ProviderError:
    status_code = getattr(exc, "status_code", None)
    message = str(exc)
    if status_code == 429 or "RESOURCE_EXHAUSTED" in message:
        return ProviderError(
            f"Gemini APIのクォータを超過しました。model={model}。"
            "無料枠・課金設定・レート制限を確認してください。"
            "開発中は --provider mock で全体の動作確認を続けられます。"
        )
    if status_code == 503 or "UNAVAILABLE" in message:
        return ProviderError(
            f"Gemini APIが一時的に混雑しています。model={model}。"
            "少し待って再実行するか、別モデルを指定してください。"
        )
    if status_code == 401 or status_code == 403 or "API key" in message:
        return ProviderError(
            "Gemini APIキーまたは権限に問題があります。"
            "GEMINI_API_KEY とGoogle AI Studio側の設定を確認してください。"
        )
    return ProviderError(f"Gemini API呼び出しに失敗しました。model={model}. detail={message}")


def _idea_from_prompt(prompt: str) -> str:
    marker = "USER_INPUT:"
    if marker in prompt:
        return prompt.split(marker, 1)[1].strip().splitlines()[0][:140]
    return "雨の街で小さなロボットが音楽に出会う"


def _mock_payload(name: str, prompt: str) -> dict:
    idea = _idea_from_prompt(prompt)
    is_mv = "OUTPUT_MODE: mv" in prompt or '"output_mode": "mv"' in prompt or "Music Video" in prompt
    platform = ""
    if "配信プラットフォーム: tiktok" in prompt:
        platform = "tiktok"
    elif "配信プラットフォーム: " in prompt:
        for line in prompt.split("\n"):
            if line.strip().startswith("配信プラットフォーム:"):
                platform = line.split(":", 1)[1].strip()
                break
    if name == "ProductionBrief":
        return {
            "title": "Rain Alley Overture",
            "logline": idea,
            "audience": "general",
            "style": "cinematic anime with grounded lighting",
            "duration_seconds": 60,
            "output_mode": "mv",
            "genre": "fantasy",
            "mood": "nostalgic",
            "color_tone": "cool",
            "narration_style": "",
            "target_platform": platform,
            "themes": ["孤独", "好奇心", "創造性の目覚め"],
            "visual_rules": ["雨の反射", "暖かいネオン", "ロボットのシルエットを固定"],
            "negative_constraints": ["動画生成はしない", "キャラクターデザインを急に変えない"],
        }
    if name == "ScriptList":
        return {
            "items": [
                {
                    "beat_id": "beat_001",
                    "summary": "配達ロボットが雨の路地で遠くの音楽を聞いて立ち止まる。",
                    "dialogue": [],
                    "emotional_purpose": "孤独と好奇心を示す。",
                },
                {
                    "beat_id": "beat_002",
                    "summary": "ロボットは自販機の下で光る壊れたオルゴールを見つける。",
                    "dialogue": ["Robot: この音の模様は何だろう。"],
                    "emotional_purpose": "発見を描く。",
                },
                {
                    "beat_id": "beat_003",
                    "summary": "ロボットが旋律を再生すると、路地の光が応答する。",
                    "dialogue": [],
                    "emotional_purpose": "変化と余韻で締める。",
                },
            ]
        }
    if name == "CharacterList":
        return {
            "items": [
                {
                    "id": "char_robot",
                    "name": "Milo",
                    "role": "the main character, a lonely delivery robot",
                    "personality": "careful, observant, quietly brave, and curious",
                    "appearance": "a small white delivery robot with a square screen face, rounded cargo shell, compact wheels, and a glowing blue status light",
                    "wardrobe": "a yellow rain poncho clipped to the cargo shell, wet from the rain",
                    "voice": "soft electronic chimes",
                    "continuity_notes": ["always show the glowing blue status light", "keep the yellow rain poncho wet and attached to the cargo shell"],
                }
            ]
        }
    if name == "SceneList":
        return {
            "items": [
                {
                    "scene_id": "scene_001",
                    "title": "雨の中の音",
                    "location": "自販機のある東京の狭い路地",
                    "time_of_day": "夜",
                    "summary": "Miloは雨がネオンを溶かす路地で音楽を聞く。",
                    "characters": ["char_robot"],
                    "beats": _mock_payload("ScriptList", prompt)["items"][:2],
                    "continuity_requirements": ["黄色いポンチョを維持", "雨は降り続ける"],
                },
                {
                    "scene_id": "scene_002",
                    "title": "路地の応答",
                    "location": "同じ路地。自販機の近く。",
                    "time_of_day": "夜",
                    "summary": "Miloが旋律を返すと、環境が光を帯びる。",
                    "characters": ["char_robot"],
                    "beats": _mock_payload("ScriptList", prompt)["items"][2:],
                    "continuity_requirements": ["同じオルゴール", "同じ青いステータスライト"],
                },
            ]
        }
    if name == "ShotList":
        return {
            "items": [
                _shot("shot_001", "scene_001", 1, "雨とネオン反射の中に立つMiloのワイドショット", "low wide angle", "24mm", "slow dolly forward"),
                _shot("shot_002", "scene_001", 2, "Miloがオルゴールを見つけるクローズアップ", "macro close-up", "50mm", "gentle rack focus"),
                _shot("shot_003", "scene_002", 3, "Miloが旋律を鳴らすと路地の光が脈打つ", "medium orbit", "35mm", "slow semicircle"),
            ]
        }
    if name == "PromptBundle":
        shots = _mock_payload("ShotList", prompt)["items"]
        aspect_ratio = _aspect_ratio_from_prompt(prompt)
        mv_note = (
            "Still-image MV edit: apply subtle Ken Burns motion toward the focal point, preserve crop-safe subtitle space, and use a soft crossfade synced to the music."
        )
        return {
            "image_prompts": [
                {
                    "shot_id": shot["shot_id"],
                    "prompt": (
                        f"Single cinematic still image, {shot['description']}. {shot['composition']}. "
                        f"Primary focal point: {shot['focal_point']}. {shot['lighting']}, cinematic anime, "
                        "layered foreground midground and background, rain reflections, "
                        "small white delivery robot with yellow rain poncho, leave clean negative space for lyrics subtitles"
                    ),
                    "negative_prompt": (
                        "multiple panels, split screen, storyboard, collage, sequence of actions, motion blur, "
                        "embedded text, subtitles, logo, watermark, inconsistent character design, extra robots, blurry face screen"
                    ),
                    "aspect_ratio": aspect_ratio,
                    "style_tags": ["cinematic anime", "rain", "neon"],
                }
                for shot in shots
            ],
            "video_prompts": [
                {
                    "shot_id": shot["shot_id"],
                    "prompt": (
                        f"{shot['still_image_intent']} Start crop: {shot['first_frame']} "
                        f"End crop: {shot['last_frame']}. {mv_note}"
                    ).strip(),
                    "duration_seconds": shot["still_duration_seconds"],
                    "camera_motion": shot["motion"],
                    "temporal_notes": (
                        "MV mode: lyrics subtitle overlay, preserve character continuity, sync visual mood to music sections."
                    ),
                }
                for shot in shots
            ],
        }
    if name == "SongSectionList":
        return {
            "items": [
                {
                    "section_id": "section_intro",
                    "label": "Intro",
                    "lyrics": [],
                    "mood": "rainy, quiet, expectant",
                    "visual_intent": "establish the neon rain world and the lonely main motif",
                    "estimated_duration_seconds": 8,
                },
                {
                    "section_id": "section_verse_1",
                    "label": "Verse 1",
                    "lyrics": ["雨の路地に光る水たまり", "小さなロボットが立ち止まる"],
                    "mood": "intimate and lonely",
                    "visual_intent": "show Milo discovering the first musical clue",
                    "estimated_duration_seconds": 18,
                },
                {
                    "section_id": "section_chorus",
                    "label": "Chorus",
                    "lyrics": ["壊れたオルゴールが歌い始める", "雨の粒が音符に変わる夜"],
                    "mood": "emotional and uplifting",
                    "visual_intent": "open the visual scale and make the street respond to the music",
                    "estimated_duration_seconds": 24,
                },
                {
                    "section_id": "section_outro",
                    "label": "Outro",
                    "lyrics": ["音はまだ路地に残る"],
                    "mood": "soft afterglow",
                    "visual_intent": "resolve on a gentle glowing final image",
                    "estimated_duration_seconds": 10,
                },
            ]
        }
    if name == "MVVisualPlanSchema":
        return {
            "concept": "A lyrics-driven miniature music video where rain, neon, and a music box turn Milo's lonely route into a glowing performance.",
            "visual_motifs": ["rain ripples", "blue status light", "music-box glow", "neon reflections"],
            "color_script": ["Intro: cool blue rain", "Verse: muted alley amber", "Chorus: blue and gold bloom", "Outro: soft cyan afterglow"],
            "pacing_notes": ["hold longer in intro", "gentle close-ups in verse", "wider glowing imagery in chorus", "slow final fade in outro"],
            "section_to_visuals": {
                "Intro": "wide lonely establishment of the rainy alley",
                "Verse 1": "intimate discovery of the music box",
                "Chorus": "street lights react like musical notes",
                "Outro": "Milo remains in the softened glow",
            },
        }
    if name == "ContinuityReport":
        return {"issues": [{"severity": "low", "location": "shot_003", "issue": "オルゴールの琥珀色の光を明示すると連続性が強くなる。", "recommendation": "shot_003とプロンプトに琥珀色の光を追記する。"}]}
    if name == "RevisionResult":
        return {"notes": ["オルゴールの琥珀色の光を継続性メモとして追加する方針にしました。"]}
    if name == "SunoMusicParamsSchema":
        improved = "YouTubeでバズる楽曲を設計する専門家" in prompt
        first_verse = "改善された歌詞一行目\n改善された歌詞二行目" if improved else "雨粒が路地でリズムを刻む\n小さな灯りが足を止める"
        chorus = "改善されたサビ一行目\n改善されたサビ二行目" if improved else "光と音が重なる夜に\n忘れていた歌を見つける"
        return {
            "lyrics": (
                "[Intro: gentle synth pad, rain ambience]\n\n"
                f"[Verse 1: soft vocals, piano]\n{first_verse}\n"
                "遠くで鳴る金属のメロディ\n心の奥に響く不思議な音\n\n"
                f"[Chorus: powerful vocals, full band]\n{chorus}\n光と音が絡み合う路地で\n"
                "小さな命が音楽を見つける\n\n"
                "[Bridge: stripped down, strings]\n旋律が路地を染めていく\nネオンが優しく脈打つ\n\n"
                "[Outro: fade out, piano only]\n雨が止み、路地に朝が来る\n\n"
                "[End]"
            ),
            "style": "cinematic electronic, mid-tempo, synth and piano, soft female vocals, polished, melancholic",
            "weirdness": 55,
            "style_influence": 85,
            "audio_influence": 50,
        }
    if name == "ViralScore":
        is_improve = "改善された" in prompt
        if is_improve:
            return {
                "scenarios": [
                    {"scenario_name": "慎重", "assumptions": "初動露出は限定的だが、サビの共有が徐々に伸びる。", "estimated_views": 1000000, "estimated_comments": 10000, "estimated_subscribers_gained": 10000},
                    {"scenario_name": "控えめ", "assumptions": "関連動画から安定して流入し、共感コメントが増える。", "estimated_views": 1100000, "estimated_comments": 12000, "estimated_subscribers_gained": 11000},
                    {"scenario_name": "標準", "assumptions": "サビの切り抜きがSNSで共有され、投稿全体へ送客する。", "estimated_views": 1250000, "estimated_comments": 15000, "estimated_subscribers_gained": 12500},
                    {"scenario_name": "好調", "assumptions": "複数のプレイリストとSNS投稿に載り、視聴が継続する。", "estimated_views": 1400000, "estimated_comments": 18000, "estimated_subscribers_gained": 14000},
                    {"scenario_name": "拡散", "assumptions": "印象的なフックが広く共有され、追加露出を獲得する。", "estimated_views": 1600000, "estimated_comments": 22000, "estimated_subscribers_gained": 16000},
                ],
                "hook_score": 19,
                "emotional_score": 20,
                "trend_score": 19,
                "universality_score": 15,
                "style_quality_score": 15,
                "retention_score": 9,
                "reasoning": "改善により慎重なシナリオでも100万再生と登録者増加1万件を見込める。",
            }
        return {
            "scenarios": [
                {"scenario_name": "慎重", "assumptions": "初動露出が弱く、関連動画からの流入も限定的。", "estimated_views": 650000, "estimated_comments": 5000, "estimated_subscribers_gained": 6500},
                {"scenario_name": "控えめ", "assumptions": "一定の共感は得るが、共有が局所的に留まる。", "estimated_views": 850000, "estimated_comments": 7500, "estimated_subscribers_gained": 8500},
                {"scenario_name": "標準", "assumptions": "サビが一部で共有され、安定した視聴を獲得する。", "estimated_views": 1050000, "estimated_comments": 12000, "estimated_subscribers_gained": 10500},
                {"scenario_name": "好調", "assumptions": "プレイリスト掲載により追加流入を獲得する。", "estimated_views": 1200000, "estimated_comments": 14000, "estimated_subscribers_gained": 12000},
                {"scenario_name": "拡散", "assumptions": "短尺切り抜きがSNSで伸び、投稿全体へ送客する。", "estimated_views": 1400000, "estimated_comments": 17000, "estimated_subscribers_gained": 14000},
            ],
            "hook_score": 18,
            "emotional_score": 18,
            "trend_score": 17,
            "universality_score": 14,
            "style_quality_score": 13,
            "retention_score": 8,
            "reasoning": "中央値では目標を満たすが、控えめなケースでは100万再生と登録者増加1万件を下回る。",
        }
    if name == "ViralChallenge":
        is_120 = "120" in prompt
        if is_120:
            return {"confirmed": True, "overestimated": False, "adjusted_score": 0, "correction_reason": ""}
        return {"confirmed": True, "overestimated": False, "adjusted_score": 0, "correction_reason": ""}
    raise ProviderError(f"mock payload が未定義です: {name}. prompt={json.dumps(prompt[:200], ensure_ascii=False)}")


def _shot(shot_id: str, scene_id: str, order: int, description: str, camera: str, lens: str, motion: str) -> dict:
    mv_captions = {
        "shot_001": "雨の路地に光る水たまり / 小さなロボットが立ち止まる",
        "shot_002": "壊れたオルゴールが歌い始める / 不思議な音の模様",
        "shot_003": "旋律が路地を染めていく / ネオンが優しく脈打つ",
    }
    caption = mv_captions.get(shot_id, "")
    still_details = {
        "shot_001": {
            "still_image_intent": "Introの孤独な世界観を一枚で提示する。",
            "composition": "Miloを左下の三分割点に置き、手前に濡れた路面、奥にネオンの路地、下部中央に字幕用の暗い余白を残す。",
            "focal_point": "Miloの青いステータスライト、画面左下",
            "still_duration_seconds": 8,
            "transition_type": "crossfade",
            "transition_duration_seconds": 0.8,
        },
        "shot_002": {
            "still_image_intent": "Verseでオルゴールとの出会いを親密な一枚として見せる。",
            "composition": "Miloと琥珀色のオルゴールを中央寄りの近景に置き、背景の自販機を柔らかくぼかし、下部に字幕用余白を残す。",
            "focal_point": "琥珀色に光るオルゴール、画面中央",
            "still_duration_seconds": 20,
            "transition_type": "crossfade",
            "transition_duration_seconds": 0.7,
        },
        "shot_003": {
            "still_image_intent": "ChorusからOutroの高揚と余韻を、路地全体が応答する一枚で締める。",
            "composition": "Miloを中央下部、光る路地を奥へ広げ、雨粒とネオンの反射で視線を奥へ導き、字幕用余白を下端に確保する。",
            "focal_point": "Miloと路地奥へ広がる青と琥珀の光、画面中央",
            "still_duration_seconds": 32,
            "transition_type": "crossfade",
            "transition_duration_seconds": 0.8,
        },
    }
    return {
        "shot_id": shot_id,
        "scene_id": scene_id,
        "order": order,
        "description": description,
        "camera": camera,
        "lens": lens,
        "motion": motion,
        "first_frame": "雨粒が反射する路面から始まる",
        "last_frame": "Miloの青いライトが画面内に残る",
        "lighting": "青い雨光と暖かい自販機の光",
        "audio": "雨音と遠いオルゴール",
        "referenced_memory": ["character:char_robot"],
        "narration_caption": caption,
        **still_details[shot_id],
    }


def _aspect_ratio_from_prompt(prompt: str) -> str:
    compact = prompt.replace(" ", "")
    if '"target_platform":"tiktok"' in compact or '"target_platform":"instagram_reel"' in compact:
        return "9:16"
    if '"target_platform":"instagram_square"' in compact:
        return "1:1"
    return "16:9"
