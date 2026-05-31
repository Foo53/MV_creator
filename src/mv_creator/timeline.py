from __future__ import annotations

import base64
import json
import re
import subprocess
from pathlib import Path
from typing import Callable
from urllib.parse import quote

from pydantic import BaseModel, Field

from mv_creator.models import ProductionDesign, ProjectPaths, ShotPlan


class TimelineTransition(BaseModel):
    type: str = "crossfade"
    duration_seconds: float = 0.5


class TimelineMotion(BaseModel):
    type: str = "slow_zoom_in"
    strength: float = 0.06


class TimelineShot(BaseModel):
    shot_id: str
    order: int
    image_path: str | None = None
    image_src: str | None = None
    status: str = "missing"
    duration_seconds: float = 5.0
    caption: str
    narration: str
    motion: TimelineMotion = Field(default_factory=TimelineMotion)
    transition: TimelineTransition = Field(default_factory=TimelineTransition)


class TimelineManifest(BaseModel):
    project: str
    title: str
    output_mode: str = "mv"
    fps: int = 30
    width: int = 1920
    height: int = 1080
    shots: list[TimelineShot] = Field(default_factory=list)
    lyrics_timeline: dict[str, list[str]] = Field(default_factory=dict)
    audio: dict[str, str | None] = Field(default_factory=lambda: {"bgm": None, "se": None, "narration": None})
    todos: list[str] = Field(default_factory=list)


class VideoRenderResult(BaseModel):
    status: str
    output_path: str | None = None
    command: list[str] = Field(default_factory=list)
    stdout: str = ""
    stderr: str = ""


def build_timeline_manifest(
    *,
    project: str,
    output_root: Path = Path("outputs"),
    fps: int = 30,
    width: int = 1920,
    height: int = 1080,
) -> TimelineManifest:
    paths = ProjectPaths.for_project(project, output_root)
    design = ProductionDesign.model_validate_json(paths.design_json.read_text(encoding="utf-8"))
    video_prompt_by_shot = {prompt.shot_id: prompt for prompt in design.video_prompts}
    shots: list[TimelineShot] = []
    for index, shot in enumerate(sorted(design.shots, key=lambda item: item.order)):
        video_prompt = video_prompt_by_shot.get(shot.shot_id)
        duration = float(video_prompt.duration_seconds if video_prompt else _default_duration(design))
        image_path = _resolve_shot_image(paths, shot.shot_id, index)
        image_exists = bool(image_path and image_path.exists())
        motion = _motion_for_shot(shot.motion, index)
        shots.append(
            TimelineShot(
                shot_id=shot.shot_id,
                order=shot.order,
                image_path=_relative_or_none(paths.root, image_path) if image_exists else None,
                image_src=_file_uri_or_none(image_path) if image_exists else None,
                status="ready" if image_exists else "missing",
                duration_seconds=duration,
                caption=_caption_for_shot(shot),
                narration=_narration_for_shot(shot.description, shot.audio, video_prompt.temporal_notes if video_prompt else ""),
                motion=motion,
            )
        )
    platform_w, platform_h = _platform_resolution(design.brief.target_platform)
    lyrics_timeline = _build_lyrics_timeline(design)
    audio = {"bgm": None, "se": None, "narration": None}
    if design.suno_params and design.suno_params.audio_path:
        audio_path = paths.root / design.suno_params.audio_path
        audio["bgm"] = _file_uri_or_none(audio_path)
    return TimelineManifest(
        project=project,
        title=design.brief.title,
        output_mode=design.brief.output_mode,
        fps=fps,
        width=width if width != 1920 or not platform_w else platform_w,
        height=height if height != 1080 or not platform_h else platform_h,
        shots=shots,
        lyrics_timeline=lyrics_timeline,
        audio=audio,
        todos=[
            "BGMトラックをtimeline_manifest.jsonへ追加し、Remotionで重ねる。",
            "SEトラックをショット単位で指定し、雨音やUI音などを追加する。",
            "TTSProviderを実装し、narrationから読み上げ音声を生成して重ねる。",
        ],
    )


def write_timeline_manifest(manifest: TimelineManifest, project: str, output_root: Path = Path("outputs")) -> Path:
    paths = ProjectPaths.for_project(project, output_root)
    target = paths.root / "timeline_manifest.json"
    target.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return target


def render_timeline_with_remotion(
    *,
    project: str,
    output_root: Path = Path("outputs"),
    repo_root: Path = Path("."),
    composition_id: str = "VimaxTimelineVideo",
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> VideoRenderResult:
    paths = ProjectPaths.for_project(project, output_root)
    manifest_path = paths.root / "timeline_manifest.json"
    if not manifest_path.exists():
        manifest = build_timeline_manifest(project=project, output_root=output_root)
        write_timeline_manifest(manifest, project, output_root)
    videos_dir = paths.root / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)
    output_path = videos_dir / "assembled_video.mp4"
    remotion_root = repo_root / "remotion"
    command = [
        "npx",
        "remotion",
        "render",
        "src/index.ts",
        composition_id,
        str(output_path.resolve()),
        "--props",
        str(manifest_path.resolve()),
    ]
    try:
        if progress_callback:
            result = _run_with_progress(command, remotion_root, progress_callback)
        else:
            result = subprocess.run(command, cwd=remotion_root, capture_output=True, text=True, timeout=900)
    except FileNotFoundError as exc:
        return _write_render_report(
            paths.root,
            VideoRenderResult(status="failed", output_path=None, command=command, stderr=f"Remotion render command failed: {exc}"),
        )
    except subprocess.TimeoutExpired as exc:
        return _write_render_report(
            paths.root,
            VideoRenderResult(status="failed", output_path=None, command=command, stdout=exc.stdout or "", stderr=exc.stderr or "Remotion render timed out."),
        )
    status = "success" if result.returncode == 0 and output_path.exists() else "failed"
    return _write_render_report(
        paths.root,
        VideoRenderResult(
            status=status,
            output_path=str(output_path) if output_path.exists() else None,
            command=command,
            stdout=result.stdout,
            stderr=result.stderr,
        ),
    )


def _run_with_progress(
    command: list[str],
    cwd: Path,
    progress_callback: Callable[[int, int, str], None],
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    stdout_lines: list[str] = []
    render_re = re.compile(r"Rendered\s+(\d+)/(\d+)")
    assert proc.stdout is not None
    for line in proc.stdout:
        stdout_lines.append(line.rstrip())
        m = render_re.search(line)
        if m:
            current = int(m.group(1))
            total = int(m.group(2))
            progress_callback(current, total, f"フレーム {current}/{total} をレンダリング中")
    proc.wait(timeout=900)
    return subprocess.CompletedProcess(args=command, returncode=proc.returncode, stdout="\n".join(stdout_lines), stderr="")


def _resolve_shot_image(paths: ProjectPaths, shot_id: str, index: int) -> Path | None:
    manual = paths.root / "images" / "manual" / f"{shot_id}.png"
    if manual.exists():
        return manual
    generated = paths.root / "images" / f"shot_{index + 1:03d}.png"
    if generated.exists():
        return generated
    return manual


def _caption_for_shot(shot: ShotPlan) -> str:
    if shot.narration_caption:
        return shot.narration_caption.strip()[:80]
    return shot.description.strip().rstrip("。.")[:80]


def _platform_resolution(target_platform: str) -> tuple[int, int]:
    mapping = {
        "tiktok": (1080, 1920),
        "instagram_reel": (1080, 1920),
        "instagram_square": (1080, 1080),
    }
    return mapping.get(target_platform, (0, 0))


def _build_lyrics_timeline(design: ProductionDesign) -> dict[str, list[str]]:
    if not design.suno_params or not design.suno_params.lyrics:
        return {}
    if design.song_sections:
        shot_ids = [shot.shot_id for shot in sorted(design.shots, key=lambda s: s.order)]
        if not shot_ids:
            return {}
        timeline: dict[str, list[str]] = {}
        for index, shot_id in enumerate(shot_ids):
            section = design.song_sections[min(index, len(design.song_sections) - 1)]
            timeline[shot_id] = [f"[{section.label}]", *section.lyrics]
        return timeline
    all_lines = [line for line in design.suno_params.lyrics.split("\n") if line.strip()]
    shot_ids = [shot.shot_id for shot in sorted(design.shots, key=lambda s: s.order)]
    if not shot_ids or not all_lines:
        return {}
    per_shot = max(1, len(all_lines) // len(shot_ids))
    timeline: dict[str, list[str]] = {}
    for i, shot_id in enumerate(shot_ids):
        start = i * per_shot
        end = start + per_shot if i < len(shot_ids) - 1 else len(all_lines)
        timeline[shot_id] = all_lines[start:end]
    return timeline


def _narration_for_shot(description: str, audio: str, temporal_notes: str) -> str:
    parts = [description.strip()]
    if audio:
        parts.append(f"音: {audio.strip()}")
    if temporal_notes:
        parts.append(temporal_notes.strip())
    return " ".join(parts)


def _motion_for_shot(raw_motion: str, index: int) -> TimelineMotion:
    lowered = raw_motion.lower()
    if "pan" in lowered:
        return TimelineMotion(type="slow_pan_right", strength=0.05)
    if "orbit" in lowered:
        return TimelineMotion(type="slow_pan_left", strength=0.05)
    if "hold" in lowered:
        return TimelineMotion(type="hold", strength=0.0)
    return TimelineMotion(type="slow_zoom_in" if index % 2 == 0 else "slow_zoom_out", strength=0.06)


def _default_duration(design: ProductionDesign) -> float:
    shot_count = max(len(design.shots), 1)
    return max(3.0, min(8.0, design.brief.duration_seconds / shot_count))


def _relative_or_none(root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _file_uri_or_none(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    suffix = path.suffix.lower()
    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".ogg": "audio/ogg",
    }
    mime = mime_map.get(suffix, "application/octet-stream")
    data = path.read_bytes()
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _write_render_report(root: Path, result: VideoRenderResult) -> VideoRenderResult:
    report = root / "videos" / "render_report.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        "\n".join(
            [
                "# Remotionレンダリングレポート",
                "",
                f"- 状態: {result.status}",
                f"- 出力: {result.output_path or 'なし'}",
                f"- コマンド: `{' '.join(result.command)}`",
                "",
                "## stdout",
                "```text",
                result.stdout,
                "```",
                "",
                "## stderr",
                "```text",
                result.stderr,
                "```",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return result
