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
from mv_creator.models import ProductionBrief, ProductionDesign, ProjectPaths, SunoMusicParams
from mv_creator.providers import MockProvider
from mv_creator.schemas import SunoMusicParamsSchema, ViralScore
from mv_creator.timeline import build_timeline_manifest, write_timeline_manifest
from mv_creator.web_app import _run_generation_job, _run_lyrics_improve_job, create_app, jobs


class PipelineTest(unittest.TestCase):
    def test_mock_provider_structured_brief(self) -> None:
        provider = MockProvider()
        brief = provider.generate_structured("USER_INPUT: test idea", ProductionBrief)
        self.assertTrue(brief.title)
        self.assertIn("test idea", brief.logline)

    def test_mock_music_generation_does_not_use_improvement_placeholder(self) -> None:
        from mv_creator.agents import MusicAgent

        result = MusicAgent(MockProvider()).run(ProductionBrief(title="t", logline="l"))
        self.assertNotIn("改善された", result.lyrics)

    def test_viral_score_normalizes_inconsistent_total(self) -> None:
        score = ViralScore(
            estimated_views=100,
            estimated_comments=10,
            estimated_subscribers_gained=1,
            total_score=999,
            hook_score=19,
            emotional_score=20,
            trend_score=19,
            universality_score=15,
            style_quality_score=15,
            retention_score=9,
            viral_bonus_score=0,
            reasoning="加点なしで合計値だけが過大",
        )
        self.assertEqual(score.total_score, 97)

    def test_viral_score_rejects_out_of_range_breakdown(self) -> None:
        with self.assertRaises(ValidationError):
            ViralScore(
                estimated_views=100,
                estimated_comments=10,
                estimated_subscribers_gained=1,
                total_score=122,
                hook_score=999,
                emotional_score=20,
                trend_score=19,
                universality_score=15,
                style_quality_score=15,
                retention_score=9,
                viral_bonus_score=0,
                reasoning="加点なしで合計値だけが過大",
            )

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
            self.assertTrue(design.video_prompts)
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
            self.assertIn("character:", output.getvalue())

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
            self.assertEqual(manifest["output_mode"], "mv")
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

    def test_narration_caption_used_in_timeline(self) -> None:
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
        self.assertEqual(brief.genre, "")
        self.assertEqual(brief.mood, "")
        self.assertEqual(brief.color_tone, "")
        self.assertEqual(brief.narration_style, "")
        self.assertEqual(brief.target_platform, "")

    def test_target_platform_sets_resolution(self) -> None:
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
                    "--target-platform",
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
            self.assertEqual(design.brief.output_mode, "mv")
            self.assertIsNotNone(design.suno_params)
            self.assertTrue(design.suno_params.lyrics)
            self.assertTrue(design.suno_params.style)
            self.assertIn("[Verse", design.suno_params.lyrics)
            self.assertIn("[Chorus", design.suno_params.lyrics)
            self.assertIn("[End]", design.suno_params.lyrics)
            self.assertTrue(any(":" in line for line in design.suno_params.lyrics.split("\n") if line.startswith("[")))
            self.assertTrue(design.song_sections)
            self.assertIsNotNone(design.mv_visual_plan)

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
                self.assertTrue(shot.narration_caption, f"{shot.shot_id} should have narration_caption in MV mode")

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
            self.assertTrue(design.video_prompts)
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
            self.assertEqual(manifest.output_mode, "mv")
            self.assertTrue(manifest.lyrics_timeline)
            for shot in manifest.shots:
                self.assertIn(shot.shot_id, manifest.lyrics_timeline)
                self.assertTrue(manifest.lyrics_timeline[shot.shot_id])

    def test_timeline_duration_matches_requested_mv_duration(self) -> None:
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
            self.assertIsNotNone(design.mv_visual_plan)
            self.assertIn("MV再設計", "\n".join(design.learning_notes))

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
                audience="general",
                style="cinematic",
                duration_seconds=60,
                genre="",
                mood="",
                color_tone="",
                narration_style="",
                target_platform="",
                provider_name="mock",
                model="mock-fixed",
                output_root=Path(temp),
            )
            result = jobs.get(job.id)
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.current, 11)
            self.assertEqual(result.total, 11)

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
                audience="general",
                style="cinematic",
                duration_seconds=60,
                genre="",
                mood="",
                color_tone="",
                narration_style="",
                target_platform="",
                provider_name="mock",
                model="mock-fixed",
                output_root=Path(temp),
            )
            result = jobs.get(job.id)
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.current, 10)
            self.assertEqual(result.total, 10)
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
                script=[], characters=[], scenes=[], shots=[],
                image_prompts=[], video_prompts=[],
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
