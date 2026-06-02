from __future__ import annotations

import json
import base64
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mv_creator.cli import main
from mv_creator.models import MVVisualPlan, ProductionBrief, ProductionDesign, ProjectPaths, SunoMusicParams
from mv_creator.providers import CodexProvider, MockProvider, _codex_strict_schema, make_provider
from mv_creator.schemas import MVVisualPlanSchema, SlideshowOutline, SunoMusicParamsSchema, ViralScore
from mv_creator.timeline import build_timeline_manifest, write_timeline_manifest
from mv_creator.web_app import _run_generation_job, _run_lyrics_improve_job, create_app, jobs


def _virtual_scenarios(values: list[tuple[int, int, int]]) -> list[dict[str, object]]:
    return [
        {
            "scenario_name": f"scenario-{index}",
            "assumptions": "test assumptions",
            "estimated_views": views,
            "estimated_comments": comments,
            "estimated_subscribers_gained": subscribers,
        }
        for index, (views, comments, subscribers) in enumerate(values, start=1)
    ]


class PipelineTest(unittest.TestCase):
    def test_codex_provider_uses_read_only_structured_exec(self) -> None:
        def fake_run(command: list[str], **kwargs):
            self.assertEqual(Path(command[0]).name, "codex.exe" if Path(command[0]).suffix else "codex")
            self.assertEqual(command[1], "exec")
            self.assertIn("--ephemeral", command)
            self.assertIn("--skip-git-repo-check", command)
            self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
            self.assertEqual(command[command.index("--model") + 1], "gpt-5.5")
            self.assertTrue(kwargs["input"].startswith("USER_INPUT:"))
            self.assertEqual(kwargs["timeout"], 600)
            output_path = Path(command[command.index("--output-last-message") + 1])
            output_path.write_text(
                json.dumps({"title": "Codex MV", "logline": "Codex generated brief"}, ensure_ascii=False),
                encoding="utf-8",
            )
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with patch("mv_creator.providers.subprocess.run", side_effect=fake_run):
            brief = CodexProvider(model="gpt-5.5").generate_structured("USER_INPUT: test", ProductionBrief)
        self.assertEqual(brief.title, "Codex MV")

    def test_codex_provider_defaults_to_gpt_5_5(self) -> None:
        provider = make_provider("codex", None)
        self.assertIsInstance(provider, CodexProvider)
        self.assertEqual(provider.model, "gpt-5.5")

    def test_codex_schema_requires_all_object_properties(self) -> None:
        schema = _codex_strict_schema(ProductionBrief.model_json_schema())
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), set(schema["properties"]))

    def test_codex_schema_supports_mv_section_visuals(self) -> None:
        schema = _codex_strict_schema(MVVisualPlanSchema.model_json_schema())
        section_visual = schema["$defs"]["MVSectionVisual"]
        self.assertFalse(section_visual["additionalProperties"])
        self.assertEqual(set(section_visual["required"]), {"section_id", "visual_direction"})

    def test_slideshow_outline_keeps_codex_payload_compact(self) -> None:
        schema = _codex_strict_schema(SlideshowOutline.model_json_schema())
        slide = schema["$defs"]["SlideshowSlide"]
        self.assertEqual(
            set(slide["properties"]),
            {"section_id", "description", "lyrics_caption", "image_prompt", "duration_seconds", "motion"},
        )

    def test_legacy_mv_section_visual_dict_is_migrated(self) -> None:
        plan = MVVisualPlan.model_validate(
            {
                "concept": "legacy",
                "section_to_visuals": {"Intro": "wide establishing shot"},
            }
        )
        self.assertEqual(plan.section_visuals[0].section_id, "Intro")
        self.assertEqual(plan.section_visuals[0].visual_direction, "wide establishing shot")

    def test_mock_provider_structured_brief(self) -> None:
        provider = MockProvider()
        brief = provider.generate_structured("USER_INPUT: test idea", ProductionBrief)
        self.assertTrue(brief.title)
        self.assertIn("test idea", brief.logline)

    def test_mock_music_generation_does_not_use_improvement_placeholder(self) -> None:
        from mv_creator.agents import MusicAgent

        result = MusicAgent(MockProvider()).run(ProductionBrief(title="t", logline="l"))
        self.assertNotIn("改善された", result.lyrics)
        self.assertEqual(result.estimated_duration_seconds, 60)

    def test_viral_score_calculates_median_and_lower_quartile(self) -> None:
        score = ViralScore(
            scenarios=_virtual_scenarios(
                [
                    (650000, 5000, 6500),
                    (850000, 7500, 8500),
                    (1050000, 12000, 10500),
                    (1200000, 14000, 12000),
                    (1400000, 17000, 14000),
                ]
            ),
            estimated_views=1,
            estimated_comments=1,
            estimated_subscribers_gained=1,
            total_score=0,
            hook_score=19,
            emotional_score=20,
            trend_score=19,
            universality_score=15,
            style_quality_score=15,
            retention_score=9,
            reasoning="中央値では達成するが、下位ケースでは未達",
        )
        self.assertEqual(score.estimated_views, 1050000)
        self.assertEqual(score.estimated_comments, 12000)
        self.assertEqual(score.estimated_subscribers_gained, 10500)
        self.assertEqual(score.lower_quartile_views, 850000)
        self.assertEqual(score.lower_quartile_subscribers_gained, 8500)
        self.assertTrue(score.achieved_100)
        self.assertFalse(score.achieved_120)
        self.assertEqual(score.total_score, 116)

    def test_viral_score_rejects_out_of_range_breakdown(self) -> None:
        with self.assertRaises(ValidationError):
            ViralScore(
                scenarios=_virtual_scenarios([(1000000, 10000, 10000)] * 5),
                hook_score=999,
                emotional_score=20,
                trend_score=19,
                universality_score=15,
                style_quality_score=15,
                retention_score=9,
                reasoning="品質内訳が範囲外",
            )

    def test_viral_score_requires_repeated_virtual_posts(self) -> None:
        with self.assertRaises(ValidationError):
            ViralScore(
                scenarios=_virtual_scenarios([(1000000, 10000, 10000)] * 4),
                hook_score=20,
                emotional_score=20,
                trend_score=20,
                universality_score=15,
                style_quality_score=15,
                retention_score=10,
                reasoning="仮想投稿数が不足",
            )

    def test_viral_score_reaches_120_only_when_lower_quartile_meets_goal(self) -> None:
        score = ViralScore(
            scenarios=_virtual_scenarios(
                [
                    (1000000, 10000, 10000),
                    (1100000, 12000, 11000),
                    (1250000, 15000, 12500),
                    (1400000, 18000, 14000),
                    (1600000, 22000, 16000),
                ]
            ),
            hook_score=19,
            emotional_score=20,
            trend_score=19,
            universality_score=15,
            style_quality_score=15,
            retention_score=9,
            reasoning="下位ケースでも目標達成",
        )
        self.assertTrue(score.achieved_100)
        self.assertTrue(score.achieved_120)
        self.assertGreaterEqual(score.total_score, 120)

    def test_create_mv_writes_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            main(
                [
                    "--output-root",
                    temp,
                    "create-mv",
                    "--project",
                    "demo",
                    "--idea",
                    "雨の中でロボットが音楽を聞く",
                    "--provider",
                    "mock",
                ]
            )
            root = Path(temp) / "demo"
            self.assertTrue((root / "design.md").exists())
            self.assertTrue((root / "design.json").exists())
            self.assertTrue((root / "rag_trace.md").exists())
            design = ProductionDesign.model_validate_json((root / "design.json").read_text(encoding="utf-8"))
            self.assertEqual(len(design.shots), 3)
            self.assertTrue(design.image_prompts)
            self.assertTrue(design.editing_prompts)
            self.assertTrue(design.learning_notes)
            self.assertEqual(design.creation_mode, "idea_to_mv")

    def test_create_mv_from_lyrics_preserves_input_lyrics(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            lyrics = "[Verse 1]\n入力済みの歌詞\n\n[Chorus]\nこの歌を映像にする\n\n[End]"
            main(
                [
                    "--output-root", temp,
                    "create-mv-from-lyrics", "--project", "lyrics-demo",
                    "--lyrics", lyrics,
                    "--music-style", "J-Pop, mid-tempo, piano and synth",
                    "--provider", "mock",
                ]
            )
            design = ProductionDesign.model_validate_json((Path(temp) / "lyrics-demo" / "design.json").read_text(encoding="utf-8"))
            self.assertEqual(design.creation_mode, "lyrics_to_mv")
            self.assertEqual(design.suno_params.lyrics, lyrics)
            self.assertEqual(design.suno_params.style, "J-Pop, mid-tempo, piano and synth")
            self.assertTrue(design.song_sections)
            self.assertTrue(design.image_prompts)

    def test_inspect_rag_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            main(
                [
                    "--output-root",
                    temp,
                    "create-mv",
                    "--project",
                    "demo",
                    "--idea",
                    "雨の中でロボットが音楽を聞く",
                    "--provider",
                    "mock",
                ]
            )
            output = StringIO()
            with redirect_stdout(output):
                main(["--output-root", temp, "inspect-rag", "--project", "demo"])
            self.assertIn('"records": []', output.getvalue())

    def test_timeline_command_writes_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            main(
                [
                    "--output-root",
                    temp,
                    "create-mv",
                    "--project",
                    "demo",
                    "--idea",
                    "雨の中でロボットが音楽を聞く",
                    "--provider",
                    "mock",
                ]
            )
            output = StringIO()
            with redirect_stdout(output):
                main(["--output-root", temp, "generate-timeline", "--project", "demo"])
            root = Path(temp) / "demo"
            manifest_path = root / "timeline_manifest.json"
            self.assertTrue(manifest_path.exists())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertNotIn("output_mode", manifest)
            self.assertEqual(len(manifest["shots"]), 3)

    def test_timeline_manifest_marks_missing_images(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            main(
                [
                    "--output-root",
                    temp,
                    "create-mv",
                    "--project",
                    "demo",
                    "--idea",
                    "雨の中でロボットが音楽を聞く",
                    "--provider",
                    "mock",
                ]
            )
            manifest = build_timeline_manifest(project="demo", output_root=Path(temp))
            self.assertEqual(manifest.shots[0].status, "missing")
            self.assertIsNone(manifest.shots[0].image_src)

    def test_lyrics_caption_used_in_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            main(
                [
                    "--output-root",
                    temp,
                    "create-mv",
                    "--project",
                    "demo",
                    "--idea",
                    "テスト",
                    "--provider",
                    "mock",
                ]
            )
            manifest = build_timeline_manifest(project="demo", output_root=Path(temp))
            for shot in manifest.shots:
                self.assertTrue(shot.caption)
                self.assertNotIn("ワイドショット", shot.caption)
                self.assertNotIn("クローズアップ", shot.caption)

    def test_production_brief_new_fields_default_empty(self) -> None:
        brief = ProductionBrief(title="t", logline="l")
        self.assertEqual(brief.music_genre, "")
        self.assertEqual(brief.music_mood, "")
        self.assertEqual(brief.visual_style, "cinematic")
        self.assertEqual(brief.visual_palette, "")
        self.assertEqual(brief.release_format, "youtube")

    def test_legacy_design_json_fields_are_migrated(self) -> None:
        design = ProductionDesign.model_validate(
            {
                "brief": {
                    "title": "legacy",
                    "logline": "legacy project",
                    "genre": "rock",
                    "mood": "energetic",
                    "style": "anime",
                    "color_tone": "neon",
                    "target_platform": "tiktok",
                },
                "script": [],
                "characters": [],
                "scenes": [],
                "shots": [
                    {
                        "shot_id": "shot_001",
                        "scene_id": "scene_001",
                        "order": 1,
                        "description": "legacy shot",
                        "camera": "wide",
                        "lens": "35mm",
                        "motion": "slow zoom",
                        "first_frame": "wide",
                        "last_frame": "medium",
                        "lighting": "neon",
                        "audio": "chorus",
                        "narration_caption": "legacy lyrics",
                    }
                ],
                "image_prompts": [],
                "video_prompts": [
                    {
                        "shot_id": "shot_001",
                        "prompt": "slow zoom",
                        "camera_motion": "push in",
                        "temporal_notes": "hold",
                    }
                ],
            }
        )
        self.assertEqual(design.brief.music_genre, "rock")
        self.assertEqual(design.brief.visual_style, "anime")
        self.assertEqual(design.brief.release_format, "tiktok")
        self.assertEqual(design.shots[0].motion_start, "wide")
        self.assertEqual(design.shots[0].lyrics_caption, "legacy lyrics")
        self.assertEqual(design.editing_prompts[0].editing_instruction, "slow zoom")
        self.assertNotIn("script", design.model_dump())
        self.assertNotIn("video_prompts", design.model_dump())

    def test_release_format_sets_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            main(
                [
                    "--output-root",
                    temp,
                    "create-mv",
                    "--project",
                    "demo",
                    "--idea",
                    "テスト",
                    "--provider",
                    "mock",
                    "--release-format",
                    "tiktok",
                ]
            )
            manifest = build_timeline_manifest(project="demo", output_root=Path(temp))
            self.assertEqual(manifest.width, 1080)
            self.assertEqual(manifest.height, 1920)
            design = ProductionDesign.model_validate_json((Path(temp) / "demo" / "design.json").read_text(encoding="utf-8"))
            self.assertTrue(all(prompt.aspect_ratio == "9:16" for prompt in design.image_prompts))

    def test_mv_mode_generates_suno_params(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            main(
                [
                    "--output-root",
                    temp,
                    "create-mv",
                    "--project",
                    "demo",
                    "--idea",
                    "テストMV",
                    "--provider",
                    "mock",
                ]
            )
            design = ProductionDesign.model_validate_json((Path(temp) / "demo" / "design.json").read_text(encoding="utf-8"))
            self.assertIsNotNone(design.suno_params)
            self.assertTrue(design.suno_params.lyrics)
            self.assertTrue(design.suno_params.style)
            self.assertIn("[Verse", design.suno_params.lyrics)
            self.assertIn("[Chorus", design.suno_params.lyrics)
            self.assertIn("[End]", design.suno_params.lyrics)
            self.assertTrue(any(":" in line for line in design.suno_params.lyrics.split("\n") if line.startswith("[")))
            self.assertTrue(design.song_sections)
            self.assertIsNone(design.mv_visual_plan)

    def test_mv_mode_lyrics_in_captions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            main(
                [
                    "--output-root",
                    temp,
                    "create-mv",
                    "--project",
                    "demo",
                    "--idea",
                    "テストMV",
                    "--provider",
                    "mock",
                ]
            )
            design = ProductionDesign.model_validate_json((Path(temp) / "demo" / "design.json").read_text(encoding="utf-8"))
            for shot in design.shots:
                self.assertTrue(shot.lyrics_caption, f"{shot.shot_id} should have lyrics_caption")

    def test_mv_mode_image_prompts_generated(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            main(
                [
                    "--output-root",
                    temp,
                    "create-mv",
                    "--project",
                    "demo",
                    "--idea",
                    "テストMV",
                    "--provider",
                    "mock",
                ]
            )
            design = ProductionDesign.model_validate_json((Path(temp) / "demo" / "design.json").read_text(encoding="utf-8"))
            self.assertTrue(design.image_prompts)
            self.assertTrue(design.editing_prompts)
            self.assertIn("MV", "\n".join(design.learning_notes))
            for shot in design.shots:
                self.assertTrue(shot.still_image_intent)
                self.assertTrue(shot.composition)
                self.assertTrue(shot.focal_point)
                self.assertGreater(shot.still_duration_seconds, 0)
            for prompt in design.image_prompts:
                self.assertIn("Single cinematic still image", prompt.prompt)
                self.assertIn("split screen", prompt.negative_prompt)
                self.assertIn("embedded text", prompt.negative_prompt)

    def test_mv_timeline_has_lyrics_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            main(
                [
                    "--output-root",
                    temp,
                    "create-mv",
                    "--project",
                    "demo",
                    "--idea",
                    "テストMV",
                    "--provider",
                    "mock",
                ]
            )
            manifest = build_timeline_manifest(project="demo", output_root=Path(temp))
            self.assertTrue(manifest.lyrics_timeline)
            for shot in manifest.shots:
                self.assertIn(shot.shot_id, manifest.lyrics_timeline)
                self.assertTrue(manifest.lyrics_timeline[shot.shot_id])

    def test_timeline_duration_matches_automatically_analyzed_song_duration(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            main(
                [
                    "--output-root", temp,
                    "create-mv", "--project", "demo",
                    "--idea", "テストMV", "--provider", "mock",
                ]
            )
            manifest = build_timeline_manifest(project="demo", output_root=Path(temp))
            self.assertAlmostEqual(sum(shot.duration_seconds for shot in manifest.shots), 60.0)
            design = ProductionDesign.model_validate_json((Path(temp) / "demo" / "design.json").read_text(encoding="utf-8"))
            self.assertEqual(design.brief.duration_seconds, 60)
            self.assertEqual(design.suno_params.estimated_duration_seconds, 60)
            self.assertIn("[Outro]", manifest.lyrics_timeline["shot_003"])
            self.assertEqual(manifest.shots[0].transition.type, "cut")
            self.assertTrue(all(shot.transition.type == "crossfade" for shot in manifest.shots[1:]))
            self.assertGreater(manifest.shots[1].motion.end_scale, 1.0)

    def test_project_name_cannot_escape_output_root(self) -> None:
        for project in ["../outside", r"..\outside", "nested/project", r"C:\outside"]:
            with self.subTest(project=project):
                with self.assertRaises(ValueError):
                    ProjectPaths.for_project(project, Path("outputs"))

    def test_suno_music_params_model_defaults(self) -> None:
        params = SunoMusicParams(lyrics="test")
        self.assertEqual(params.weirdness, 50)
        self.assertEqual(params.style_influence, 80)
        self.assertEqual(params.audio_influence, 50)
        self.assertEqual(params.estimated_duration_seconds, 0)
        self.assertIsNone(params.audio_path)

    def test_music_audio_upload_saves_file(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp:
            main(
                [
                    "--output-root", temp,
                    "create-mv", "--project", "demo",
                    "--idea", "テストMV", "--provider", "mock",
                ]
            )
            client = TestClient(create_app(Path(temp)))
            response = client.post(
                "/projects/demo/music/upload-audio",
                files={"file": ("bgm.mp3", b"fake-mp3-data", "audio/mpeg")},
            )
            self.assertEqual(response.status_code, 200)
            audio_path = Path(temp) / "demo" / "music" / "bgm.mp3"
            self.assertTrue(audio_path.exists())
            self.assertEqual(audio_path.read_bytes(), b"fake-mp3-data")
            design = ProductionDesign.model_validate_json((Path(temp) / "demo" / "design.json").read_text(encoding="utf-8"))
            self.assertEqual(design.suno_params.audio_path, "music/bgm.mp3")

    def test_music_save_preserves_uploaded_audio_path(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp:
            main(
                [
                    "--output-root", temp,
                    "create-mv", "--project", "demo",
                    "--idea", "テストMV", "--provider", "mock",
                ]
            )
            client = TestClient(create_app(Path(temp)))
            client.post(
                "/projects/demo/music/upload-audio",
                files={"file": ("bgm.mp3", b"fake-mp3-data", "audio/mpeg")},
            )
            response = client.post(
                "/projects/demo/music/save",
                data={
                    "lyrics": "[Verse]\n新しい歌詞\n[End]",
                    "style": "J-Pop, bright synth, female vocals",
                    "weirdness": "35",
                    "style_influence": "85",
                    "audio_influence": "60",
                },
            )
            self.assertEqual(response.status_code, 200)
            design = ProductionDesign.model_validate_json((Path(temp) / "demo" / "design.json").read_text(encoding="utf-8"))
            self.assertEqual(design.suno_params.audio_path, "music/bgm.mp3")

    def test_music_save_invalidates_stale_mv_visual_design(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp:
            main(
                [
                    "--output-root", temp,
                    "create-mv", "--project", "demo",
                    "--idea", "テストMV", "--provider", "mock",
                ]
            )
            manifest = build_timeline_manifest(project="demo", output_root=Path(temp))
            timeline_path = write_timeline_manifest(manifest, "demo", Path(temp))
            client = TestClient(create_app(Path(temp)))
            response = client.post(
                "/projects/demo/music/save",
                data={
                    "lyrics": "[Verse]\n新しい歌詞\n[End]",
                    "style": "J-Pop, bright synth, female vocals",
                    "weirdness": "35",
                    "style_influence": "85",
                    "audio_influence": "60",
                },
            )

            self.assertEqual(response.status_code, 200)
            design = ProductionDesign.model_validate_json((Path(temp) / "demo" / "design.json").read_text(encoding="utf-8"))
            self.assertFalse(design.song_sections)
            self.assertIsNone(design.mv_visual_plan)
            self.assertFalse(design.shots)
            self.assertFalse(timeline_path.exists())

    def test_timeline_manifest_includes_uploaded_bgm_data_uri(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp:
            main(
                [
                    "--output-root", temp,
                    "create-mv", "--project", "demo",
                    "--idea", "テストMV", "--provider", "mock",
                ]
            )
            client = TestClient(create_app(Path(temp)))
            client.post(
                "/projects/demo/music/upload-audio",
                files={"file": ("bgm.mp3", b"fake-mp3-data", "audio/mpeg")},
            )
            manifest = build_timeline_manifest(project="demo", output_root=Path(temp))
            self.assertTrue(manifest.audio["bgm"].startswith("data:audio/mpeg;base64,"))

    def test_rebuild_mv_visuals_uses_existing_suno_params(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            main(
                [
                    "--output-root", temp,
                    "create-mv", "--project", "demo",
                    "--idea", "テストMV", "--provider", "mock",
                ]
            )
            main(["--output-root", temp, "rebuild-mv-visuals", "--project", "demo", "--provider", "mock"])
            design = ProductionDesign.model_validate_json((Path(temp) / "demo" / "design.json").read_text(encoding="utf-8"))
            self.assertTrue(design.song_sections)
            self.assertIsNone(design.mv_visual_plan)
            self.assertIn("画像スライド再設計", "\n".join(design.learning_notes))

    def test_web_generation_job_completes_with_mock_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            job = jobs.create("web-demo")
            _run_generation_job(
                job_id=job.id,
                project="web-demo",
                creation_mode="idea_to_mv",
                idea="テストMV",
                lyrics="",
                music_style="",
                visual_style="cinematic",
                music_genre="",
                music_mood="",
                visual_palette="",
                release_format="youtube",
                provider_name="mock",
                model="mock-fixed",
                output_root=Path(temp),
            )
            result = jobs.get(job.id)
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.current, 5)
            self.assertEqual(result.total, 5)

    def test_web_generation_job_from_lyrics_preserves_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            lyrics = "[Verse]\nWebから入力した歌詞\n\n[End]"
            job = jobs.create("web-lyrics-demo")
            _run_generation_job(
                job_id=job.id,
                project="web-lyrics-demo",
                creation_mode="lyrics_to_mv",
                idea="",
                lyrics=lyrics,
                music_style="acoustic pop, soft vocals",
                visual_style="cinematic",
                music_genre="",
                music_mood="",
                visual_palette="",
                release_format="youtube",
                provider_name="mock",
                model="mock-fixed",
                output_root=Path(temp),
            )
            result = jobs.get(job.id)
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.current, 4)
            self.assertEqual(result.total, 4)
            design = ProductionDesign.model_validate_json((Path(temp) / "web-lyrics-demo" / "design.json").read_text(encoding="utf-8"))
            self.assertEqual(design.creation_mode, "lyrics_to_mv")
            self.assertEqual(design.suno_params.lyrics, lyrics)
            self.assertEqual(design.suno_params.style, "acoustic pop, soft vocals")

    def test_web_shot_page_uploads_chatgpt_image(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp:
            main(
                [
                    "--output-root", temp,
                    "create-mv", "--project", "demo",
                    "--idea", "テストMV", "--provider", "mock",
                ]
            )
            client = TestClient(create_app(Path(temp)))
            project_response = client.get("/projects/demo")
            self.assertEqual(project_response.status_code, 200)
            self.assertIn("画像プロンプト・アップロード", project_response.text)
            shots_response = client.get("/projects/demo/shots")
            self.assertEqual(shots_response.status_code, 200)
            self.assertIn("ChatGPT貼り付け用プロンプト", shots_response.text)
            image_data = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
            )
            upload_response = client.post(
                "/projects/demo/shots/shot_001/upload",
                files={"file": ("shot.png", image_data, "image/png")},
            )
            self.assertEqual(upload_response.status_code, 200)
            self.assertTrue((Path(temp) / "demo" / "images" / "manual" / "shot_001.png").exists())
            manifest = build_timeline_manifest(project="demo", output_root=Path(temp))
            self.assertEqual(manifest.shots[0].status, "ready")

    def test_web_home_offers_both_creation_modes(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp:
            client = TestClient(create_app(Path(temp)))
            response = client.get("/")
            self.assertEqual(response.status_code, 200)
            self.assertIn("idea_to_mv", response.text)
            self.assertIn("lyrics_to_mv", response.text)
            self.assertIn("music_genre", response.text)
            self.assertIn("music_mood", response.text)
            self.assertIn("visual_palette", response.text)
            self.assertIn("release_format", response.text)
            self.assertIn('<option value="codex">codex</option>', response.text)
            self.assertIn('data-provider="codex"', response.text)
            self.assertNotIn('name="duration_seconds"', response.text)
            self.assertNotIn("audience", response.text)
            self.assertNotIn("narration_style", response.text)

    def test_web_lyrics_mode_requires_lyrics(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp:
            client = TestClient(create_app(Path(temp)))
            response = client.post(
                "/projects/generate",
                data={"project": "demo", "creation_mode": "lyrics_to_mv", "lyrics": ""},
            )
            self.assertEqual(response.status_code, 400)

    def test_improve_lyrics_job_returns_improved_params(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            main(
                [
                    "--output-root", temp,
                    "create-mv", "--project", "demo",
                    "--idea", "テストMV", "--provider", "mock",
                ]
            )
            from fastapi.testclient import TestClient
            client = TestClient(create_app(Path(temp)))
            response = client.post(
                "/projects/demo/music/improve-lyrics",
                data={"provider": "mock", "model": "mock-fixed"},
            )
            self.assertEqual(response.status_code, 200)
            job_id = response.json()["job_id"]
            import time
            for _ in range(20):
                job_resp = client.get(f"/api/jobs/{job_id}")
                job_data = job_resp.json()
                if job_data["status"] in ("completed", "failed"):
                    break
                time.sleep(0.1)
            self.assertEqual(job_data["status"], "completed")
            self.assertIsNotNone(job_data["result_data"])
            self.assertIn("lyrics", job_data["result_data"])
            self.assertIn("style", job_data["result_data"])
            self.assertIn("weirdness", job_data["result_data"])
            self.assertTrue(job_data["result_data"]["lyrics"])
            self.assertTrue(job_data["result_data"]["target_achieved"])
            self.assertGreaterEqual(job_data["result_data"]["lower_quartile_views"], 1000000)
            self.assertGreaterEqual(job_data["result_data"]["lower_quartile_subscribers_gained"], 10000)

    def test_improve_lyrics_job_uses_current_form_params(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            main(
                [
                    "--output-root", temp,
                    "create-mv", "--project", "demo",
                    "--idea", "テストMV", "--provider", "mock",
                ]
            )
            job = jobs.create("demo")
            received: dict[str, SunoMusicParams] = {}

            def fake_run(self, brief, suno_params, *, progress_callback=None):
                received["suno_params"] = suno_params
                return SunoMusicParamsSchema(
                    lyrics=suno_params.lyrics,
                    style=suno_params.style,
                    weirdness=suno_params.weirdness,
                    style_influence=suno_params.style_influence,
                    audio_influence=suno_params.audio_influence,
                )

            with patch("mv_creator.agents.LyricImproverAgent.run", fake_run):
                _run_lyrics_improve_job(
                    job_id=job.id,
                    project="demo",
                    provider_name="mock",
                    model="mock-fixed",
                    output_root=Path(temp),
                    lyrics="[Verse]\n未保存の編集中歌詞\n[End]",
                    style="unsaved style",
                    weirdness=41,
                    style_influence=72,
                    audio_influence=63,
                )

            params = received["suno_params"]
            self.assertIn("未保存の編集中歌詞", params.lyrics)
            self.assertEqual(params.style, "unsaved style")
            self.assertEqual(params.weirdness, 41)
            self.assertEqual(params.style_influence, 72)
            self.assertEqual(params.audio_influence, 63)

    def test_improve_lyrics_fails_without_suno_params(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            main(["--output-root", temp, "init", "--project", "empty"])
            from mv_creator.models import ProjectPaths
            paths = ProjectPaths.for_project("empty", Path(temp))
            from mv_creator.models import ProductionDesign, ProductionBrief, SunoMusicParams
            design = ProductionDesign(
                brief=ProductionBrief(title="t", logline="l"),
                mv_beats=[], characters=[], scenes=[], shots=[],
                image_prompts=[], editing_prompts=[],
            )
            paths.design_json.write_text(design.model_dump_json(indent=2), encoding="utf-8")
            from fastapi.testclient import TestClient
            client = TestClient(create_app(Path(temp)))
            response = client.post(
                "/projects/empty/music/improve-lyrics",
                data={"provider": "mock", "model": "mock-fixed"},
            )
            job_id = response.json()["job_id"]
            import time
            for _ in range(20):
                job_resp = client.get(f"/api/jobs/{job_id}")
                job_data = job_resp.json()
                if job_data["status"] in ("completed", "failed"):
                    break
                time.sleep(0.1)
            self.assertEqual(job_data["status"], "failed")

    def test_improve_lyrics_loop_passes_100_and_reaches_120(self) -> None:
        from mv_creator.agents import LyricImproverAgent
        from mv_creator.providers import MockProvider

        provider = MockProvider()
        agent = LyricImproverAgent(provider)
        brief = ProductionBrief(title="テスト", logline="テストログライン", duration_seconds=60)
        suno_params = SunoMusicParams(lyrics="[Verse]\nテスト歌詞\n[End]", style="pop, upbeat")
        events: list[str] = []

        def progress(message: str, iteration: int, max_iterations: int) -> None:
            events.append(message)

        result = agent.run(brief, suno_params, progress_callback=progress)
        self.assertTrue(result.lyrics)
        self.assertTrue(result.style)
        self.assertIn("weirdness", result.model_dump())
        has_100_phase = any("100点目標" in e for e in events)
        has_120_phase = any("120点目標" in e for e in events)
        has_completed = any("検証OK" in e for e in events)
        self.assertTrue(has_100_phase, f"100点目標フェーズがない: {events}")
        self.assertTrue(has_120_phase, f"120点目標フェーズがない: {events}")
        self.assertTrue(has_completed, f"検証完了がない: {events}")

    def test_improve_lyrics_loop_reports_unmet_target_after_max_iterations(self) -> None:
        from mv_creator.agents import LyricImproverAgent

        agent = LyricImproverAgent(MockProvider())
        brief = ProductionBrief(title="テスト", logline="テストログライン", duration_seconds=60)
        suno_params = SunoMusicParams(lyrics="[Verse]\nテスト歌詞\n[End]", style="pop, upbeat")
        low_score = ViralScore(
            scenarios=_virtual_scenarios([(500000, 4000, 5000)] * 5),
            hook_score=10,
            emotional_score=10,
            trend_score=10,
            universality_score=8,
            style_quality_score=8,
            retention_score=5,
            reasoning="目標未達",
        )
        events: list[str] = []

        with (
            patch.object(agent, "_evaluate", return_value=low_score),
            patch.object(agent, "_improve", return_value=suno_params),
        ):
            agent.run(brief, suno_params, progress_callback=lambda message, iteration, max_iterations: events.append(message))

        self.assertFalse(agent.last_target_achieved)
        self.assertIs(agent.last_score, low_score)
        self.assertTrue(any("目標未達" in event for event in events))

    def test_improve_lyrics_job_reports_iteration_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            main(
                [
                    "--output-root", temp,
                    "create-mv", "--project", "demo",
                    "--idea", "テストMV", "--provider", "mock",
                ]
            )
            from fastapi.testclient import TestClient
            client = TestClient(create_app(Path(temp)))
            response = client.post(
                "/projects/demo/music/improve-lyrics",
                data={"provider": "mock", "model": "mock-fixed"},
            )
            job_id = response.json()["job_id"]
            import time
            for _ in range(30):
                job_resp = client.get(f"/api/jobs/{job_id}")
                job_data = job_resp.json()
                if job_data["status"] in ("completed", "failed"):
                    break
                time.sleep(0.1)
            self.assertEqual(job_data["status"], "completed")
            self.assertIn("lyrics", job_data["result_data"])
            self.assertIn("改善", job_data["result_data"]["lyrics"])
if __name__ == "__main__":
    unittest.main()
