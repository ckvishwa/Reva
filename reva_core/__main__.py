"""`python -m reva_core` entry point.

Default behavior: load config, init logging, bootstrap storage/migrations,
report healthy startup, shut down cleanly, exit 0. This is the Phase 0
smoke-testable contract.

`--serve` additionally binds the loopback-only FastAPI app and blocks
until interrupted (Ctrl+C), then shuts down cleanly.
"""

from __future__ import annotations

import argparse
import sys

from reva_core.config.settings import load_settings
from reva_core.orchestration.lifecycle import CoreLifecycle
from reva_core.shared.errors import ConfigurationError
from reva_core.shared.logging import configure_logging, get_logger


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="reva_core")
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Bind the loopback-only health/version API and block until interrupted.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    try:
        settings = load_settings()
    except ConfigurationError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 1

    configure_logging(level=settings.log_level)
    logger = get_logger("main")
    lifecycle = CoreLifecycle(settings)

    try:
        health = lifecycle.startup()
        logger.info("reva core healthy", extra={"status": health.status.value})

        if args.serve:
            import uvicorn

            from reva_core.api.app import create_app

            app = create_app(lifecycle)
            uvicorn.run(app, host=settings.api_host, port=settings.api_port, log_config=None)
        return 0
    finally:
        lifecycle.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
