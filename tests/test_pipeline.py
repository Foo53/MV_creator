from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mv_creator.cli import main
from mv_creator.models import ProductionBrief, ProductionDesign, SunoMusicParams
from mv_creator.providers import MockProvider
from mv_creator.timeline import build_timeline_manifest
from mv_creator.web_app import create_app, jobs


class PipelineTest(unittest.TestCase):
    def test_mock_provider_structured_brief(self) -> None:
        provider = MockProvider()
        brief = provider.generate_structured("USER_INPUT: test idea", ProductionBrief)
        self.assertTrue(brief.title)
        self.assertIn("test idea", brief.logline)

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


if __name__ == "__main__":
    unittest.main()
