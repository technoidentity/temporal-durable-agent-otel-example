"""Run the demo UI control plane.

    python -m app.entrypoints.ui            # serves on :8000 (config ui.port)
    python -m app.entrypoints.ui --port 8080
"""

from __future__ import annotations

import click
import uvicorn

from app.config import load_settings
from app.ui.server import create_ui_app


@click.command()
@click.option("--host", default=None)
@click.option("--port", type=int, default=None)
def main(host, port) -> None:
    settings = load_settings()
    app = create_ui_app(settings)
    uvicorn.run(
        app,
        host=host or settings.ui.host,
        port=port or settings.ui.port,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
