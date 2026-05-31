from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, UnidentifiedImageError

from mv_creator.models import ProductionDesign, ProjectPaths, SunoMusicParams
from mv_creator.pipeline import rebuild_mv_visual_design, run_idea_pipeline, run_lyrics_pipeline
from mv_creator.providers import ProviderError, make_provider
from mv_creator.timeline import build_timeline_manifest, render_timeline_with_remotion, write_timeline_manifest


@dataclass
class JobState:
    id: str
    project: str
    status: str = "queued"
    stage: str = "queued"
    message: str = "待機中です"
    current: int = 0
    total: int = 1
    error: str | None = None
    result_url: str | None = None
    result_data: dict | None = None
    events: list[str] = field(default_factory=list)

    @property
    def percent(self) -> int:
        if self.total <= 0:
            return 0
        return min(100, int(self.current / self.total * 100))


class JobStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, JobState] = {}

    def create(self, project: str) -> JobState:
        job = JobState(id=str(uuid.uuid4()), project=project)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> JobState:
        with self._lock:
            return self._jobs[job_id]

    def update(self, job_id: str, **kwargs: Any) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for key, value in kwargs.items():
                setattr(job, key, value)
            if "message" in kwargs:
                job.events.append(str(kwargs["message"]))


jobs = JobStore()


AUDIENCE_OPTIONS = [
    {"value": "general", "label": "一般視聴者"},
    {"value": "children", "label": "子ども向け"},
    {"value": "young_adults", "label": "若年層・SNS向け"},
    {"value": "film_fans", "label": "映画好き・映像表現重視"},
    {"value": "tech_portfolio", "label": "採用担当・技術ポートフォリオ向け"},
]


MODEL_OPTIONS = [
    {"value": "mock-fixed", "label": "Mock 固定応答（APIなし）", "provider": "mock"},
    {"value": "gemini-2.5-flash", "label": "Gemini 2.5 Flash", "provider": "gemini"},
    {"value": "gemini-2.5-pro", "label": "Gemini 2.5 Pro", "provider": "gemini"},
    {"value": "gemini-2.0-flash", "label": "Gemini 2.0 Flash", "provider": "gemini"},
    {"value": "claude-cli", "label": "Claude Code CLI", "provider": "claude"},
]


DURATION_PRESETS = [15, 30, 45, 60, 90, 120, 180, 300]

GENRE_OPTIONS = [
    {"value": "", "label": "指定しない"},
    {"value": "fantasy", "label": "ファンタジー"},
    {"value": "slice_of_life", "label": "日常系"},
    {"value": "documentary", "label": "ドキュメンタリー"},
    {"value": "corporate", "label": "企業・PR"},
    {"value": "horror", "label": "ホラー・サスペンス"},
    {"value": "comedy", "label": "コメディ"},
    {"value": "poetic", "label": "詩的・実験的"},
]

MOOD_OPTIONS = [
    {"value": "", "label": "指定しない"},
    {"value": "bright", "label": "明るい・希望"},
    {"value": "dark", "label": "暗い・重厚"},
    {"value": "nostalgic", "label": "ノスタルジック"},
    {"value": "energetic", "label": "エネルギッシュ"},
    {"value": "calm", "label": "穏やか・静謐"},
    {"value": "mysterious", "label": "神秘的"},
    {"value": "whimsical", "label": "ゆかい・不思議"},
]

COLOR_TONE_OPTIONS = [
    {"value": "", "label": "指定しない"},
    {"value": "warm", "label": "暖色系"},
    {"value": "cool", "label": "寒色系"},
    {"value": "monochrome", "label": "モノクロ"},
    {"value": "vivid", "label": "ビビッド"},
    {"value": "pastel", "label": "パステル"},
    {"value": "muted", "label": "くすみ・アンティーク"},
]

NARRATION_STYLE_OPTIONS = [
    {"value": "", "label": "絵本風（デフォルト）"},
    {"value": "third_person", "label": "三人称ナレーション"},
    {"value": "first_person", "label": "一人称（主人公の語り）"},
    {"value": "dialogue", "label": "セリフ中心"},
    {"value": "none", "label": "字幕なし"},
]

TARGET_PLATFORM_OPTIONS = [
    {"value": "", "label": "指定しない（16:9）"},
    {"value": "youtube", "label": "YouTube 横長（16:9）"},
    {"value": "tiktok", "label": "TikTok 縦長（9:16）"},
    {"value": "instagram_square", "label": "Instagram 正方形（1:1）"},
    {"value": "instagram_reel", "label": "Instagram Reel（9:16）"},
    {"value": "twitter", "label": "X/Twitter（16:9）"},
]

STYLE_OPTIONS = [
    {"value": "cinematic", "label": "シネマティック"},
    {"value": "anime", "label": "アニメ"},
    {"value": "watercolor", "label": "水彩画風"},
    {"value": "oil_painting", "label": "油絵風"},
    {"value": "pixel_art", "label": "ピクセルアート"},
    {"value": "photorealistic", "label": "フォトリアル"},
    {"value": "flat_design", "label": "フラットデザイン"},
    {"value": "3d_render", "label": "3Dレンダー"},
    {"value": "stop_motion", "label": "ストップモーション風"},
    {"value": "minimal", "label": "ミニマル"},
    {"value": "retro", "label": "レトロ・ノスタルジー"},
    {"value": "cyberpunk", "label": "サイバーパンク"},
    {"value": "studio_ghibli", "label": "ジブリ風"},
    {"value": "manga", "label": "漫画風"},
]


def _load_design(paths: ProjectPaths) -> ProductionDesign:
    return ProductionDesign.model_validate_json(paths.design_json.read_text(encoding="utf-8"))


def _invalidate_mv_visual_design(design: ProductionDesign, paths: ProjectPaths) -> None:
    design.script = []
    design.characters = []
    design.scenes = []
    design.shots = []
    design.image_prompts = []
    design.video_prompts = []
    design.continuity_issues = []
    design.rag_trace = []
    design.song_sections = []
    design.mv_visual_plan = None
    design.learning_notes.append("音楽設定変更: 古いMV映像設計を無効化しました。映像設計を再生成してください。")
    (paths.root / "timeline_manifest.json").unlink(missing_ok=True)


def _shot_image_path(paths: ProjectPaths, shot_id: str, index: int) -> Path | None:
    manual = paths.images / "manual" / f"{shot_id}.png"
    if manual.exists():
        return manual
    generated = paths.images / f"shot_{index + 1:03d}.png"
    return generated if generated.exists() else None


def _project_counts(paths: ProjectPaths, design: ProductionDesign) -> dict[str, int]:
    shots = sorted(design.shots, key=lambda item: item.order)
    generated = sum(1 for index, shot in enumerate(shots) if _shot_image_path(paths, shot.shot_id, index))
    return {"total": len(design.shots), "generated": generated, "remaining": len(design.shots) - generated}


def create_app(output_root: Path = Path("outputs")) -> FastAPI:
    app = FastAPI(title="MV Creator Web UI")
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
    output_root.mkdir(parents=True, exist_ok=True)
    app.mount("/files", StaticFiles(directory=str(output_root)), name="files")

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> HTMLResponse:
        projects = sorted(path.name for path in output_root.iterdir() if (path / "design.json").exists())
        return templates.TemplateResponse(
            request,
            "home.html",
            {
                "projects": projects,
                "audience_options": AUDIENCE_OPTIONS,
                "model_options": MODEL_OPTIONS,
                "duration_presets": DURATION_PRESETS,
                "genre_options": GENRE_OPTIONS,
                "mood_options": MOOD_OPTIONS,
                "color_tone_options": COLOR_TONE_OPTIONS,
                "narration_style_options": NARRATION_STYLE_OPTIONS,
                "target_platform_options": TARGET_PLATFORM_OPTIONS,
                "style_options": STYLE_OPTIONS,
            },
        )

    @app.post("/projects/generate")
    def generate_project(
        project: str = Form(...),
        creation_mode: str = Form("idea_to_mv"),
        idea: str = Form(""),
        lyrics: str = Form(""),
        music_style: str = Form(""),
        audience: str = Form("general"),
        style: str = Form("cinematic"),
        duration_seconds: int = Form(60),
        genre: str = Form(""),
        mood: str = Form(""),
        color_tone: str = Form(""),
        narration_style: str = Form(""),
        target_platform: str = Form(""),
        provider: str = Form("mock"),
        model: str = Form("gemini-2.5-flash"),
    ) -> RedirectResponse:
        if creation_mode == "lyrics_to_mv":
            if not lyrics.strip():
                raise HTTPException(status_code=400, detail="歌詞入力モードでは歌詞が必要です。")
        elif creation_mode == "idea_to_mv":
            if not idea.strip():
                raise HTTPException(status_code=400, detail="アイデア入力モードではアイデアが必要です。")
        else:
            raise HTTPException(status_code=400, detail="未知の制作モードです。")
        job = jobs.create(project)
        thread = threading.Thread(
            target=_run_generation_job,
            kwargs={
                "job_id": job.id,
                "project": project,
                "creation_mode": creation_mode,
                "idea": idea,
                "lyrics": lyrics,
                "music_style": music_style,
                "audience": audience,
                "style": style,
                "duration_seconds": duration_seconds,
                "genre": genre,
                "mood": mood,
                "color_tone": color_tone,
                "narration_style": narration_style,
                "target_platform": target_platform,
                "provider_name": provider,
                "model": model,
                "output_root": output_root,
            },
            daemon=True,
        )
        thread.start()
        return RedirectResponse(f"/jobs/{job.id}", status_code=303)

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    def job_page(request: Request, job_id: str) -> HTMLResponse:
        return templates.TemplateResponse(request, "job.html", {"job": jobs.get(job_id)})

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str) -> dict[str, Any]:
        job = jobs.get(job_id)
        return {
            "id": job.id,
            "project": job.project,
            "status": job.status,
            "stage": job.stage,
            "message": job.message,
            "current": job.current,
            "total": job.total,
            "percent": job.percent,
            "error": job.error,
            "result_url": job.result_url,
            "result_data": job.result_data,
            "events": job.events[-8:],
        }

    @app.get("/projects/{project}", response_class=HTMLResponse)
    def project_page(request: Request, project: str) -> HTMLResponse:
        paths = ProjectPaths.for_project(project, output_root)
        design = _load_design(paths)
        timeline_path = paths.root / "timeline_manifest.json"
        video_path = paths.root / "videos" / "assembled_video.mp4"
        return templates.TemplateResponse(
            request,
            "project.html",
            {
                "project": project,
                "design": design,
                "counts": _project_counts(paths, design),
                "timeline_exists": timeline_path.exists(),
                "video_exists": video_path.exists(),
                "is_mv": True,
            },
        )

    @app.get("/projects/{project}/shots", response_class=HTMLResponse)
    def shots_page(request: Request, project: str) -> HTMLResponse:
        paths = ProjectPaths.for_project(project, output_root)
        design = _load_design(paths)
        prompt_by_shot = {prompt.shot_id: prompt for prompt in design.image_prompts}
        shot_rows = []
        for index, shot in enumerate(sorted(design.shots, key=lambda item: item.order)):
            image_path = _shot_image_path(paths, shot.shot_id, index)
            shot_rows.append(
                {
                    "shot": shot,
                    "prompt": prompt_by_shot.get(shot.shot_id),
                    "image_url": f"/files/{project}/{image_path.relative_to(paths.root).as_posix()}" if image_path else None,
                }
            )
        return templates.TemplateResponse(
            request,
            "shots.html",
            {"project": project, "shot_rows": shot_rows, "counts": _project_counts(paths, design)},
        )

    @app.post("/projects/{project}/shots/{shot_id}/upload")
    async def upload_shot_image(project: str, shot_id: str, file: UploadFile = File(...)) -> RedirectResponse:
        paths = ProjectPaths.for_project(project, output_root)
        design = _load_design(paths)
        if shot_id not in {shot.shot_id for shot in design.shots}:
            raise HTTPException(status_code=404, detail="指定されたショットは存在しません。")
        data = await file.read()
        try:
            with Image.open(BytesIO(data)) as image:
                image.load()
                target = paths.images / "manual" / f"{shot_id}.png"
                target.parent.mkdir(parents=True, exist_ok=True)
                image.convert("RGB").save(target, format="PNG")
        except (UnidentifiedImageError, OSError):
            raise HTTPException(status_code=400, detail="画像ファイルを読み込めませんでした。")
        return RedirectResponse(f"/projects/{project}/shots#{shot_id}", status_code=303)

    @app.post("/projects/{project}/timeline")
    def create_timeline(project: str) -> RedirectResponse:
        manifest = build_timeline_manifest(project=project, output_root=output_root)
        write_timeline_manifest(manifest, project, output_root)
        return RedirectResponse(f"/projects/{project}", status_code=303)

    @app.post("/projects/{project}/render-video")
    def render_video(project: str) -> RedirectResponse:
        job = jobs.create(project)
        thread = threading.Thread(
            target=_run_render_job,
            kwargs={
                "job_id": job.id,
                "project": project,
                "output_root": output_root,
                "repo_root": Path.cwd(),
            },
            daemon=True,
        )
        thread.start()
        return RedirectResponse(f"/jobs/{job.id}", status_code=303)

    @app.get("/projects/{project}/music", response_class=HTMLResponse)
    def music_page(request: Request, project: str) -> HTMLResponse:
        paths = ProjectPaths.for_project(project, output_root)
        design = _load_design(paths)
        suno_params = design.suno_params
        if not suno_params:
            suno_params = SunoMusicParams(lyrics="")
        audio_url = f"/files/{project}/{suno_params.audio_path}" if suno_params.audio_path else None
        return templates.TemplateResponse(request, "music.html", {"project": project, "design": design, "suno": suno_params, "audio_url": audio_url, "model_options": MODEL_OPTIONS})

    @app.post("/projects/{project}/music/save")
    async def save_music_params(request: Request, project: str) -> RedirectResponse:
        paths = ProjectPaths.for_project(project, output_root)
        design = _load_design(paths)
        form = await request.form()
        existing_audio_path = design.suno_params.audio_path if design.suno_params else None
        updated_suno_params = SunoMusicParams(
            lyrics=str(form.get("lyrics", "")),
            style=str(form.get("style", "")),
            weirdness=int(str(form.get("weirdness", "50"))),
            style_influence=int(str(form.get("style_influence", "80"))),
            audio_influence=int(str(form.get("audio_influence", "50"))),
            audio_path=existing_audio_path,
        )
        if design.suno_params != updated_suno_params:
            _invalidate_mv_visual_design(design, paths)
        design.suno_params = updated_suno_params
        paths.design_json.write_text(design.model_dump_json(indent=2), encoding="utf-8")
        return RedirectResponse(f"/projects/{project}/music", status_code=303)

    @app.post("/projects/{project}/music/regenerate")
    async def regenerate_music_params(request: Request, project: str) -> RedirectResponse:
        from mv_creator.agents import MusicAgent

        paths = ProjectPaths.for_project(project, output_root)
        design = _load_design(paths)
        form = await request.form()
        message = str(form.get("message", ""))
        provider_name = str(form.get("provider", "mock"))
        model = str(form.get("model", "gemini-2.5-flash"))
        provider = make_provider(provider_name, model)
        existing_audio_path = design.suno_params.audio_path if design.suno_params else None
        suno_params = MusicAgent(provider).run(design.brief, message=message)
        suno_params.audio_path = existing_audio_path
        _invalidate_mv_visual_design(design, paths)
        design.suno_params = suno_params
        paths.design_json.write_text(design.model_dump_json(indent=2), encoding="utf-8")
        return RedirectResponse(f"/projects/{project}/music", status_code=303)

    @app.post("/projects/{project}/music/rebuild-visuals")
    async def rebuild_music_visuals(request: Request, project: str) -> RedirectResponse:
        form = await request.form()
        provider_name = str(form.get("provider", "mock"))
        model = str(form.get("model", "gemini-2.5-flash"))
        job = jobs.create(project)
        thread = threading.Thread(
            target=_run_mv_rebuild_job,
            kwargs={
                "job_id": job.id,
                "project": project,
                "provider_name": provider_name,
                "model": model,
                "output_root": output_root,
            },
            daemon=True,
        )
        thread.start()
        return RedirectResponse(f"/jobs/{job.id}", status_code=303)

    @app.post("/projects/{project}/music/improve-lyrics")
    async def improve_lyrics(request: Request, project: str) -> dict[str, str]:
        form = await request.form()
        provider_name = str(form.get("provider", "mock"))
        model = str(form.get("model", "gemini-2.5-flash"))
        lyrics = str(form["lyrics"]) if "lyrics" in form else None
        style = str(form["style"]) if "style" in form else None
        weirdness = int(str(form["weirdness"])) if "weirdness" in form else None
        style_influence = int(str(form["style_influence"])) if "style_influence" in form else None
        audio_influence = int(str(form["audio_influence"])) if "audio_influence" in form else None
        job = jobs.create(project)
        thread = threading.Thread(
            target=_run_lyrics_improve_job,
            kwargs={
                "job_id": job.id,
                "project": project,
                "provider_name": provider_name,
                "model": model,
                "lyrics": lyrics,
                "style": style,
                "weirdness": weirdness,
                "style_influence": style_influence,
                "audio_influence": audio_influence,
                "output_root": output_root,
            },
            daemon=True,
        )
        thread.start()
        return {"job_id": job.id}

    @app.post("/projects/{project}/music/upload-audio")
    async def upload_music_audio(project: str, file: UploadFile = File(...)) -> RedirectResponse:
        paths = ProjectPaths.for_project(project, output_root)
        design = _load_design(paths)
        music_dir = paths.root / "music"
        music_dir.mkdir(parents=True, exist_ok=True)
        data = await file.read()
        ext = Path(file.filename or "audio.mp3").suffix.lower() or ".mp3"
        if ext not in {".mp3", ".wav", ".m4a", ".aac", ".ogg"}:
            raise HTTPException(status_code=400, detail="対応していない音楽ファイル形式です。")
        audio_filename = f"bgm{ext}"
        (music_dir / audio_filename).write_bytes(data)
        if design.suno_params:
            design.suno_params.audio_path = f"music/{audio_filename}"
        else:
            design.suno_params = SunoMusicParams(audio_path=f"music/{audio_filename}")
        paths.design_json.write_text(design.model_dump_json(indent=2), encoding="utf-8")
        return RedirectResponse(f"/projects/{project}/music#audio-section", status_code=303)

    return app


def _run_generation_job(
    *,
    job_id: str,
    project: str,
    creation_mode: str,
    idea: str,
    lyrics: str,
    music_style: str,
    audience: str,
    style: str,
    duration_seconds: int,
    genre: str,
    mood: str,
    color_tone: str,
    narration_style: str,
    target_platform: str,
    provider_name: str,
    model: str,
    output_root: Path,
) -> None:
    total = 10 if creation_mode == "lyrics_to_mv" else 11
    jobs.update(job_id, status="running", message="制作設計を開始しました", current=0, total=total)

    def progress(stage: str, message: str, current: int, total: int) -> None:
        jobs.update(job_id, stage=stage, message=message, current=current, total=total)

    try:
        provider = make_provider(provider_name, model)
        common_args = {
            "project": project,
            "provider": provider,
            "output_root": output_root,
            "audience": audience,
            "style": style,
            "duration_seconds": duration_seconds,
            "genre": genre,
            "mood": mood,
            "color_tone": color_tone,
            "narration_style": narration_style,
            "target_platform": target_platform,
            "progress": progress,
        }
        if creation_mode == "lyrics_to_mv":
            run_lyrics_pipeline(lyrics=lyrics, music_style=music_style, **common_args)
        else:
            run_idea_pipeline(idea=idea, **common_args)
        jobs.update(
            job_id,
            status="completed",
            stage="completed",
            message="制作設計が完了しました",
            current=total,
            total=total,
            result_url=f"/projects/{project}",
        )
    except ProviderError as exc:
        jobs.update(job_id, status="failed", stage="failed", message="Providerエラーで停止しました", error=str(exc))
    except Exception as exc:
        jobs.update(job_id, status="failed", stage="failed", message="予期しないエラーで停止しました", error=str(exc))


def _run_lyrics_improve_job(
    *,
    job_id: str,
    project: str,
    provider_name: str,
    model: str,
    output_root: Path,
    lyrics: str | None = None,
    style: str | None = None,
    weirdness: int | None = None,
    style_influence: int | None = None,
    audio_influence: int | None = None,
) -> None:
    from mv_creator.agents import LyricImproverAgent

    jobs.update(job_id, status="running", stage="improve-lyrics", message="歌詞改善を開始しています", current=0, total=10)
    try:
        paths = ProjectPaths.for_project(project, output_root)
        design = _load_design(paths)
        if not design.suno_params:
            jobs.update(job_id, status="failed", stage="failed", message="歌詞がまだ生成されていません", error="suno_params is None")
            return
        provider = make_provider(provider_name, model)
        current_params = design.suno_params.model_copy(deep=True)
        if lyrics is not None:
            current_params.lyrics = lyrics
        if style is not None:
            current_params.style = style
        if weirdness is not None:
            current_params.weirdness = weirdness
        if style_influence is not None:
            current_params.style_influence = style_influence
        if audio_influence is not None:
            current_params.audio_influence = audio_influence

        def progress(message: str, iteration: int, max_iterations: int) -> None:
            jobs.update(job_id, stage="improve-lyrics", message=message, current=iteration, total=max_iterations)

        result = LyricImproverAgent(provider).run(design.brief, current_params, progress_callback=progress)
        jobs.update(
            job_id,
            status="completed",
            stage="completed",
            message="歌詞の改善が完了しました",
            current=10,
            total=10,
            result_data={
                "lyrics": result.lyrics,
                "style": result.style,
                "weirdness": result.weirdness,
                "style_influence": result.style_influence,
                "audio_influence": result.audio_influence,
            },
        )
    except ProviderError as exc:
        jobs.update(job_id, status="failed", stage="failed", message="Providerエラーで停止しました", error=str(exc))
    except Exception as exc:
        jobs.update(job_id, status="failed", stage="failed", message="歌詞改善に失敗しました", error=str(exc))


def _run_mv_rebuild_job(
    *,
    job_id: str,
    project: str,
    provider_name: str,
    model: str,
    output_root: Path,
) -> None:
    jobs.update(job_id, status="running", stage="mv-rebuild", message="MV映像設計の再生成を開始しました", current=0, total=7)

    def progress(stage: str, message: str, current: int, total: int) -> None:
        jobs.update(job_id, stage=stage, message=message, current=current, total=total)

    try:
        provider = make_provider(provider_name, model)
        rebuild_mv_visual_design(
            project=project,
            provider=provider,
            output_root=output_root,
            progress=progress,
        )
        timeline = build_timeline_manifest(project=project, output_root=output_root)
        write_timeline_manifest(timeline, project, output_root)
        jobs.update(
            job_id,
            status="completed",
            stage="completed",
            message="Suno歌詞・styleに準拠したMV映像設計を再生成しました",
            current=7,
            total=7,
            result_url=f"/projects/{project}",
        )
    except ProviderError as exc:
        jobs.update(job_id, status="failed", stage="failed", message="Providerエラーで停止しました", error=str(exc))
    except Exception as exc:
        jobs.update(job_id, status="failed", stage="failed", message="MV映像設計の再生成に失敗しました", error=str(exc))


def _run_render_job(
    *,
    job_id: str,
    project: str,
    output_root: Path,
    repo_root: Path,
) -> None:
    jobs.update(job_id, status="running", stage="preparing", message="タイムラインを準備しています", current=0, total=1)

    def progress(current: int, total: int, message: str) -> None:
        jobs.update(job_id, stage="rendering", message=message, current=current, total=max(total, 1))

    try:
        result = render_timeline_with_remotion(
            project=project,
            output_root=output_root,
            repo_root=repo_root,
            progress_callback=progress,
        )
        if result.status == "success":
            jobs.update(
                job_id,
                status="completed",
                stage="completed",
                message="動画の書き出しが完了しました",
                current=result.stdout.count("Rendered") if result.stdout else 1,
                total=result.stdout.count("Rendered") if result.stdout else 1,
                result_url=f"/projects/{project}",
            )
        else:
            jobs.update(
                job_id,
                status="failed",
                stage="failed",
                message="動画の書き出しに失敗しました",
                error=result.stderr or "Remotionレンダリングエラー",
            )
    except Exception as exc:
        jobs.update(job_id, status="failed", stage="failed", message="動画の書き出しに失敗しました", error=str(exc))


def run_web_app(host: str, port: int, output_root: Path) -> None:
    import uvicorn

    uvicorn.run(create_app(output_root), host=host, port=port)
