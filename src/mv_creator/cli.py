from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mv_creator.models import ProjectPaths
from mv_creator.pipeline import (
    init_project,
    rebuild_mv_visual_design,
    revise_existing_design,
    run_idea_pipeline,
)
from mv_creator.providers import ProviderError, make_provider
from mv_creator.rag import RAGStore
from mv_creator.timeline import build_timeline_manifest, render_timeline_with_remotion, write_timeline_manifest


def main(argv: list[str] | None = None) -> None:
    _load_dotenv_if_available()
    parser = argparse.ArgumentParser(prog="mv-creator")
    parser.add_argument("--output-root", default="outputs")
    sub = parser.add_subparsers(dest="command", required=True)

    init_cmd = sub.add_parser("init")
    init_cmd.add_argument("--project", required=True)

    create_mv_cmd = sub.add_parser("create-mv")
    _add_common_generation_args(create_mv_cmd)
    create_mv_cmd.add_argument("--idea", required=True)

    revise_cmd = sub.add_parser("revise")
    _add_provider_args(revise_cmd)
    revise_cmd.add_argument("--project", required=True)

    rebuild_mv_cmd = sub.add_parser("rebuild-mv-visuals")
    _add_provider_args(rebuild_mv_cmd)
    rebuild_mv_cmd.add_argument("--project", required=True)

    inspect_cmd = sub.add_parser("inspect-rag")
    inspect_cmd.add_argument("--project", required=True)

    timeline_cmd = sub.add_parser("generate-timeline")
    timeline_cmd.add_argument("--project", required=True)
    timeline_cmd.add_argument("--fps", type=int, default=30)
    timeline_cmd.add_argument("--width", type=int, default=1920)
    timeline_cmd.add_argument("--height", type=int, default=1080)

    render_video_cmd = sub.add_parser("render-video")
    render_video_cmd.add_argument("--project", required=True)
    render_video_cmd.add_argument("--renderer", choices=["remotion"], default="remotion")

    web_cmd = sub.add_parser("web")
    web_cmd.add_argument("--host", default="127.0.0.1")
    web_cmd.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    output_root = Path(args.output_root)

    if args.command == "init":
        paths = ProjectPaths.for_project(args.project, output_root)
        init_project(paths)
        print(f"プロジェクトを初期化しました: {paths.root}")
        return

    if args.command == "create-mv":
        provider = make_provider(args.provider, args.model)
        try:
            design = run_idea_pipeline(
                idea=args.idea,
                project=args.project,
                provider=provider,
                output_root=output_root,
                audience=args.audience,
                style=args.style,
                duration_seconds=args.duration_seconds,
                genre=args.genre,
                mood=args.mood,
                color_tone=args.color_tone,
                narration_style=args.narration_style,
                target_platform=args.target_platform,
            )
        except ProviderError as exc:
            _print_provider_error(exc)
            return
        _print_done(args.project, output_root, design)
        return

    if args.command == "revise":
        provider = make_provider(args.provider, args.model)
        try:
            design = revise_existing_design(project=args.project, provider=provider, output_root=output_root)
        except ProviderError as exc:
            _print_provider_error(exc)
            return
        print(f"修正が完了しました。継続性指摘数: {len(design.continuity_issues)}")
        return

    if args.command == "rebuild-mv-visuals":
        provider = make_provider(args.provider, args.model)
        try:
            design = rebuild_mv_visual_design(project=args.project, provider=provider, output_root=output_root)
        except ProviderError as exc:
            _print_provider_error(exc)
            return
        print(f"MV映像設計を再生成しました: {len(design.shots)} shots")
        return

    if args.command == "inspect-rag":
        paths = ProjectPaths.for_project(args.project, output_root)
        rag = RAGStore(paths.rag_store)
        print(json.dumps({"records": [record.__dict__ for record in rag.records]}, ensure_ascii=False, indent=2))
        return

    if args.command == "generate-timeline":
        manifest = build_timeline_manifest(
            project=args.project,
            output_root=output_root,
            fps=args.fps,
            width=args.width,
            height=args.height,
        )
        target = write_timeline_manifest(manifest, args.project, output_root)
        ready = sum(1 for shot in manifest.shots if shot.status == "ready")
        print(f"タイムラインを生成しました: {target}")
        print(f"使用可能画像: {ready}/{len(manifest.shots)}")
        return

    if args.command == "render-video":
        result = render_timeline_with_remotion(project=args.project, output_root=output_root, repo_root=Path.cwd())
        if result.status == "success":
            print(f"Remotion動画を生成しました: {result.output_path}")
        else:
            print("Remotion動画生成に失敗しました。outputs/<project>/videos/render_report.md を確認してください。", file=sys.stderr)
            print("依存関係が未導入の場合は remotion/ で npm install を実行してください。", file=sys.stderr)
        return

    if args.command == "web":
        from mv_creator.web_app import run_web_app

        run_web_app(args.host, args.port, output_root)
        return


def _add_provider_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--provider", choices=["gemini", "claude", "mock"], default="mock")
    parser.add_argument("--model", default="gemini-2.5-flash")


def _add_common_generation_args(parser: argparse.ArgumentParser) -> None:
    _add_provider_args(parser)
    parser.add_argument("--project", required=True)
    parser.add_argument("--audience", default="general")
    parser.add_argument("--style", default="cinematic")
    parser.add_argument("--duration-seconds", type=int, default=60)
    parser.add_argument("--genre", default="")
    parser.add_argument("--mood", default="")
    parser.add_argument("--color-tone", default="")
    parser.add_argument("--narration-style", default="")
    parser.add_argument("--target-platform", default="")


def _print_done(project: str, output_root: Path, design) -> None:
    paths = ProjectPaths.for_project(project, output_root)
    print(f"制作設計を生成しました: {paths.design_json}")
    print(f"ショット数: {len(design.shots)} / 継続性指摘数: {len(design.continuity_issues)}")


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError:
        return
    load_dotenv()


def _print_provider_error(exc: ProviderError) -> None:
    print(f"エラー: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
