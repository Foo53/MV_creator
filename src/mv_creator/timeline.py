from __future__ import annotations

import base64
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Callable
from urllib.parse import quote

from pydantic import BaseModel, Field

from mv_creator.models import ProductionDesign, ProjectPaths, ShotPlan, SongSection


class TimelineTransition(BaseModel):
    type: str = "crossfade"
    duration_seconds: float = 0.6


class TimelineMotion(BaseModel):
    type: str = "slow_zoom_in"
    start_scale: float = 1.02
    end_scale: float = 1.08
    start_x_percent: float = 0.0
    end_x_percent: float = 0.0
    start_y_percent: float = 0.0
    end_y_percent: float = 0.0


class TimelineShot(BaseModel):
    shot_id: str
    order: int
    image_path: str | None = None
    image_src: str | None = None
    status: str = "missing"
    duration_seconds: float = 5.0
    caption: str
    editing_notes: str
    motion: TimelineMotion = Field(default_factory=TimelineMotion)
    transition: TimelineTransition = Field(default_factory=TimelineTransition)


class TimelineManifest(BaseModel):
    project: str
    title: str
    fps: int = 30
    width: int = 1920
    height: int = 1080
    shots: list[TimelineShot] = Field(default_factory=list)
    lyrics_timeline: dict[str, list[str]] = Field(default_factory=dict)
    audio: dict[str, str | None] = Field(default_factory=lambda: {"bgm": None})


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
    editing_prompt_by_shot = {prompt.shot_id: prompt for prompt in design.editing_prompts}
    shots: list[TimelineShot] = []
    ordered_shots = sorted(design.shots, key=lambda item: item.order)
    durations = _normalized_shot_durations(design, ordered_shots)
    for index, shot in enumerate(ordered_shots):
        editing_prompt = editing_prompt_by_shot.get(shot.shot_id)
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
                duration_seconds=durations[index],
                caption=_caption_for_shot(shot),
                editing_notes=_editing_notes_for_shot(shot.description, shot.music_sync_notes, editing_prompt.temporal_notes if editing_prompt else ""),
                motion=motion,
                transition=TimelineTransition(
                    type="cut" if index == 0 else shot.transition_type,
                    duration_seconds=0.0 if index == 0 or shot.transition_type == "cut" else shot.transition_duration_seconds,
                ),
            )
        )
    platform_w, platform_h = _format_resolution(design.brief.release_format)
    lyrics_timeline = _build_lyrics_timeline(design, shots)
    audio = {"bgm": None}
    if design.suno_params and design.suno_params.audio_path:
        audio_path = paths.root / design.suno_params.audio_path
        audio["bgm"] = _file_uri_or_none(audio_path)
    return TimelineManifest(
        project=project,
        title=design.brief.title,
        fps=fps,
        width=width if width != 1920 or not platform_w else platform_w,
        height=height if height != 1080 or not platform_h else platform_h,
        shots=shots,
        lyrics_timeline=lyrics_timeline,
        audio=audio,
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
    composition_id: str = "MVTimelineVideo",
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
    local_remotion = remotion_root / "node_modules" / ".bin" / ("remotion.cmd" if os.name == "nt" else "remotion")
    runner = [str(local_remotion)] if local_remotion.exists() else ["npx", "remotion"]
    command = [
        *runner,
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
            result = subprocess.run(
                command,
                cwd=remotion_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=900,
            )
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
    proc = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
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
    if shot.lyrics_caption:
        return shot.lyrics_caption.strip()[:80]
    return shot.description.strip().rstrip("。.")[:80]


def _format_resolution(release_format: str) -> tuple[int, int]:
    mapping = {
        "tiktok": (1080, 1920),
        "youtube_shorts": (1080, 1920),
        "instagram_reel": (1080, 1920),
    }
    return mapping.get(release_format, (0, 0))


def _build_lyrics_timeline(design: ProductionDesign, shots: list[TimelineShot]) -> dict[str, list[str]]:
    if not design.suno_params or not design.suno_params.lyrics:
        return {}
    if design.song_sections:
        if not shots:
            return {}
        section_durations = [max(0, section.estimated_duration_seconds) for section in design.song_sections]
        if not any(section_durations):
            section_durations = [1] * len(design.song_sections)
        section_scale = sum(shot.duration_seconds for shot in shots) / sum(section_durations)
        section_ranges: list[tuple[float, float, SongSection]] = []
        section_elapsed = 0.0
        for section, duration in zip(design.song_sections, section_durations):
            start = section_elapsed
            section_elapsed += duration * section_scale
            section_ranges.append((start, section_elapsed, section))
        timeline: dict[str, list[str]] = {}
        elapsed = 0.0
        for shot in shots:
            shot_end = elapsed + shot.duration_seconds
            lines: list[str] = []
            for start, end, section in section_ranges:
                if start < shot_end and end > elapsed:
                    lines.extend([f"[{section.label}]", *section.lyrics])
            timeline[shot.shot_id] = lines
            elapsed = shot_end
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


def _editing_notes_for_shot(description: str, music_sync_notes: str, temporal_notes: str) -> str:
    parts = [description.strip()]
    if music_sync_notes:
        parts.append(f"楽曲同期: {music_sync_notes.strip()}")
    if temporal_notes:
        parts.append(temporal_notes.strip())
    return " ".join(parts)


def _motion_for_shot(raw_motion: str, index: int) -> TimelineMotion:
    lowered = raw_motion.lower()
    if "pan left" in lowered:
        return TimelineMotion(type="slow_pan_left", start_scale=1.1, end_scale=1.1, start_x_percent=2.5, end_x_percent=-2.5)
    if "pan right" in lowered:
        return TimelineMotion(type="slow_pan_right", start_scale=1.1, end_scale=1.1, start_x_percent=-2.5, end_x_percent=2.5)
    if "pan up" in lowered:
        return TimelineMotion(type="slow_pan_up", start_scale=1.1, end_scale=1.1, start_y_percent=2.5, end_y_percent=-2.5)
    if "pan down" in lowered:
        return TimelineMotion(type="slow_pan_down", start_scale=1.1, end_scale=1.1, start_y_percent=-2.5, end_y_percent=2.5)
    if "pan" in lowered:
        return TimelineMotion(type="slow_pan_right", start_scale=1.1, end_scale=1.1, start_x_percent=-2.5, end_x_percent=2.5)
    if "orbit" in lowered:
        return TimelineMotion(type="slow_pan_left", start_scale=1.1, end_scale=1.1, start_x_percent=2.0, end_x_percent=-2.0)
    if "hold" in lowered:
        return TimelineMotion(type="hold", start_scale=1.03, end_scale=1.03)
    if "zoom out" in lowered:
        return TimelineMotion(type="slow_zoom_out", start_scale=1.1, end_scale=1.02)
    return TimelineMotion(type="slow_zoom_in" if index % 2 == 0 else "slow_zoom_out", start_scale=1.02, end_scale=1.08)


def _default_duration(design: ProductionDesign) -> float:
    shot_count = max(len(design.shots), 1)
    return max(3.0, min(8.0, design.brief.duration_seconds / shot_count))


def _normalized_shot_durations(
    design: ProductionDesign,
    shots: list[ShotPlan],
) -> list[float]:
    durations = [shot.still_duration_seconds or _default_duration(design) for shot in shots]
    total = sum(durations)
    target = float(design.brief.duration_seconds)
    if total <= 0 or target <= 0:
        return durations
    scale = target / total
    return [duration * scale for duration in durations]


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
