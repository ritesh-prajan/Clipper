"""Entry point for running the Clipper web app: python -m clipper.web"""

import argparse
import logging
import os
import sys
from pathlib import Path

import uvicorn

from clipper.web.app import create_app

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("clipper.web")


def parse_args():
    parser = argparse.ArgumentParser(description="Clipper Web App - Local-first AI Video Clipper")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    parser.add_argument("--output-dir", default="./live_output", help="Root output directory (default: ./live_output)")
    parser.add_argument("--db-path", default=None, help="Custom SQLite db path")
    parser.add_argument("--password", default=None, help="Set login password (forces auth requirement)")
    parser.add_argument("--reload", action="store_true", help="Enable uvicorn reload")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.password:
        os.environ["CLIPPER_PASSWORD"] = args.password

    output_dir = Path(args.output_dir)
    db_path = Path(args.db_path) if args.db_path else None

    logger.info("Initializing Clipper Web App on http://%s:%d ...", args.host, args.port)
    app = create_app(
        output_dir=output_dir,
        db_path=db_path,
        bind_host=args.host,
    )

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
