"""CLI entry: python -m pc_transfer"""

from __future__ import annotations

import argparse
import os
import threading
import time
import webbrowser

import uvicorn

from .registry import Registry
from .server import create_app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="PC Transfer — LAN game + save sync")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default 0.0.0.0 for LAN)")
    parser.add_argument("--port", type=int, default=None, help="HTTP port (default from settings)")
    parser.add_argument("--name", default=None, help="Device display name")
    parser.add_argument("--role", choices=["main", "handheld"], default=None)
    parser.add_argument("--data-dir", default=None, help="Override data directory")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the UI in a browser")
    parser.add_argument("--headless", action="store_true", help="Disable native folder picker")
    args = parser.parse_args(argv)

    if args.data_dir:
        os.environ["PC_TRANSFER_DATA"] = args.data_dir
    if args.role:
        os.environ["PC_TRANSFER_ROLE"] = args.role
    if args.name:
        os.environ["PC_TRANSFER_NAME"] = args.name
    if args.headless:
        os.environ["PC_TRANSFER_HEADLESS"] = "1"

    registry = Registry()
    if args.name or args.role:
        kwargs = {}
        if args.name:
            kwargs["device_name"] = args.name
        if args.role:
            kwargs["role"] = args.role
        registry.update_settings(**kwargs)
    if args.port:
        registry.update_settings(http_port=args.port)

    port = registry.settings.http_port
    app = create_app(registry)

    if not args.no_browser and os.environ.get("PC_TRANSFER_HEADLESS") != "1":
        def _open() -> None:
            time.sleep(0.8)
            webbrowser.open(f"http://127.0.0.1:{port}/")

        threading.Thread(target=_open, daemon=True).start()

    print(f"PC Transfer listening on http://{args.host}:{port}/")
    print(f"Device: {registry.settings.device_name} ({registry.settings.role.value})")
    print(f"Data:   {registry.data_dir}")
    print("Controller: D-pad/Left-stick navigate · A confirm · B back · Y refresh · X verify")
    uvicorn.run(app, host=args.host, port=port, log_level="info")


if __name__ == "__main__":
    main()
