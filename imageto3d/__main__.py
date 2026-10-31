"""Command line entry: a local server, or a one-shot conversion."""

from __future__ import annotations

import argparse
import os
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
        description="画像1枚から、このPCの中だけで3Dモデルを作ります。推定はGPUを優先します。",
    )
    sub = parser.add_subparsers(dest="command")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--device",
        choices=("auto", "cuda", "cpu"),
        default="auto",
        help="推定に使う装置。auto は GPU があれば CUDA、無ければ CPU",
    )

    app = sub.add_parser("app", parents=[common], help="サーバーとウィンドウをまとめて起動する")
    app.add_argument("--host", default="127.0.0.1")
    app.add_argument("--port", type=int, default=7860)

    serve = sub.add_parser("serve", parents=[common], help="ブラウザで使えるローカルアプリを起動する")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=7860)
    serve.add_argument("--open", action="store_true", help="起動後にブラウザを開く")

    convert = sub.add_parser("convert", parents=[common], help="画像を3Dファイルに変換する")
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
    sub.add_parser("install", help="このPCのアプリメニューとコマンドにインストールする")
    package = sub.add_parser("package", help="配布用の wheel と Debian パッケージを作る")
    package.add_argument("-o", "--output", type=Path, default=None, help="出力先。省略すると dist/")

    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        argv = ["app"]
    args = parser.parse_args(argv)
    if getattr(args, "device", None):
        os.environ["IMAGETO3D_DEVICE"] = args.device
    if args.command in {None, "app"}:
        return _launch_app(getattr(args, "host", "127.0.0.1"), getattr(args, "port", 7860))
    if args.command == "install":
        return _install()
    if args.command == "package":
        return _package(args.output)
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


def _package(output: Path | None) -> int:
    from .packaging import build_distribution

    try:
        created = build_distribution(output)
    except RuntimeError as error:
        print(f"パッケージを作成できません: {error}", file=sys.stderr)
        return 1
    print("パッケージを作成しました:")
    for path in created:
        print(f"  {path}")
    return 0


def _install() -> int:
    from .installer import install

    try:
        result = install()
    except RuntimeError as error:
        print(f"インストールに失敗しました: {error}", file=sys.stderr)
        return 1
    print(result["message"])
    for note in result.get("notes", []):
        print(f"  {note}")
    return 0


def _launch_app(host: str, port: int) -> int:
    from .launch import (
        is_ready,
        open_app_window,
        run_server,
        stop_server,
        wait_until_ready,
    )

    sample = WEB_DIR / "sample.png"
    if not sample.is_file():
        write_sample(sample)
    url = f"http://{host}:{port}"
    server = None
    thread = None
    if is_ready(url):
        print(f"すでに起動しています: {url}")
    else:
        print("画像から3Dを起動しています")
        server, thread = run_server(host, port)
        if not wait_until_ready(url):
            print(f"起動できませんでした: {url}", file=sys.stderr)
            stop_server(server, thread)
            return 1
        print(f"開いています: {url}")
    window = open_app_window(url)
    if window is None:
        print("表示できるブラウザが見つかりません。上のアドレスを開いてください。")
        if server is None:
            return 0
        try:
            while thread.is_alive():
                thread.join(timeout=0.4)
        except KeyboardInterrupt:
            pass
        stop_server(server, thread)
        return 0
    try:
        code = window.wait()
    except KeyboardInterrupt:
        window.terminate()
        code = 0
    if server is not None and thread is not None:
        stop_server(server, thread)
    return 0 if code == 0 else 1


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
        result.mesh.vertex_normals
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
    from .device import current

    device = current()
    if device is not None:
        print(f"推定: {device.label}")
    print(
        f"保存しました: {destination}（頂点 {result.vertices:,} / 面 {result.faces:,} / {result.elapsed_s:.1f}秒）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
