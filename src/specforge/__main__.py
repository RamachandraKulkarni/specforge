"""Entry point: python -m specforge"""

import os
import sys
import asyncio
import argparse
from pathlib import Path

import uvicorn
from dotenv import load_dotenv


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(
        prog="specforge",
        description="SpecForge v2 — Automated UI Spec Generation Pipeline",
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Host to bind the server to"
    )
    parser.add_argument(
        "--port", type=int, default=int(os.getenv("PORT", 8000)), help="Port to listen on"
    )
    parser.add_argument(
        "--config", default="config.yaml", help="Path to config.yaml"
    )
    parser.add_argument(
        "--reload", action="store_true", help="Enable auto-reload (dev mode)"
    )
    args = parser.parse_args()

    os.environ["SPECFORGE_CONFIG"] = args.config

    uvicorn.run(
        "specforge.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
