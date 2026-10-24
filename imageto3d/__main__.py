"""Command line entry: a local server, or a one-shot conversion."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .bundle import save_bundle
from .download import ensure_models
from .paths import WEB_DIR
from .pipeline import Settings, open_image, reconstruct
from .sample_art import write_sample


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="imageto3d",
        description="画像1枚から、このPCの中だけで3Dモデルを作ります。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="ブラウザで使えるローカルアプリを起動する")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=7860)
    serve.add_argument("--open", action="store_true", help="起動後にブラウザを開く")

    convert = sub.add_parser("convert", help="画像を3Dファイルに変換する")
    convert.add_argument("image", type=Path)
    convert.add_argument("-o", "--output", type=Path, required=True, help=".glb / .stl / .obj / .zip")
    convert.add_argument("--mode", choices=("volume", "relief"), default="volume")
    convert.add_argument("--no-cutout", action="store_true")
    convert.add_argument("--resolution", type=int, default=220)
    convert.add_argument("--depth-scale", type=float, default=0.22)
    convert.add_argument("--inflate", type=float, default=0.46)
    convert.add_argument("--thickness", type=float, default=0.08)
    convert.add_argument("--smooth", type=float, default=1.0)

    sub.add_parser("download-models", help="深度モデルと切り抜きモデルを取得する")

    args = parser.parse_args(argv)
    if args.command == "download-models":
        return _download()
    if args.command == "serve":
        return _serve(args.host, args.port, args.open)
    return _convert(args)


def _download() -> int:
    def progress(model, written, total):
        if total:
            percent = written / total * 100
            print(f"\r{model.filename}: {percent:5.1f}%", end="", flush=True)
        else:
            print(f"{model.filename} を取得しています", flush=True)

    try:
        paths = ensure_models(progress=progress)
    except Exception as error:
        print(f"\n失敗しました: {error}", file=sys.stderr)
        return 1
    print("\n準備できました:")
    for path in paths:
        print(f"  {path}")
    return 0


def _serve(host: str, port: int, open_browser: bool) -> int:
    import uvicorn

    sample = WEB_DIR / "sample.png"
    if not sample.is_file():
        write_sample(sample)
    if open_browser:
        import threading
        import webbrowser

        threading.Timer(0.8, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    uvicorn.run("imageto3d.server:app", host=host, port=port, log_level="info")
    return 0


def _convert(args) -> int:
    source: Path = args.image
    if not source.is_file():
        print(f"画像がありません: {source}", file=sys.stderr)
        return 1
    suffix = args.output.suffix.lower()
    if suffix not in {".glb", ".stl", ".obj", ".zip"}:
        print("出力は .glb .stl .obj .zip のいずれかです", file=sys.stderr)
        return 1
    print("モデルを確認しています")
    try:
        ensure_models(progress=lambda model, written, total: None)
    except Exception as error:
        print(f"モデルを準備できません: {error}", file=sys.stderr)
        return 1
    try:
        image = open_image(source.read_bytes())
        result = reconstruct(
            image,
            Settings(
                mode=args.mode,
                cutout=not args.no_cutout,
                resolution=args.resolution,
                depth_scale=args.depth_scale,
                inflate=args.inflate,
                thickness=args.thickness,
                smooth=args.smooth,
            ),
            on_status=print,
        )
    except Exception as error:
        print(f"変換に失敗しました: {error}", file=sys.stderr)
        return 1

    destination = args.output
    destination.parent.mkdir(parents=True, exist_ok=True)
    if suffix == ".glb":
        result.mesh.export(destination)
    elif suffix == ".stl":
        import trimesh

        trimesh.Trimesh(result.mesh.vertices.copy(), result.mesh.faces.copy(), process=False).export(destination)
    else:
        folder = destination.with_suffix("")
        save_bundle(result.mesh, folder)
        if suffix == ".zip":
            packaged = folder / "model-obj.zip"
            packaged.replace(destination)
        else:
            (folder / "model.obj").replace(destination)
            print(f"テクスチャ: {folder / 'texture.png'}")
            print(f"マテリアル: {folder / 'model.mtl'}")
    if result.notice:
        print(result.notice)
    print(
        f"保存しました: {destination}（頂点 {result.vertices:,} / 面 {result.faces:,} / {result.elapsed_s:.1f}秒）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
