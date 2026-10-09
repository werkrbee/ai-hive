"""Run the server: python -m hive_a2a --config config.toml [--host 0.0.0.0] [--port 8080]"""
import argparse
import logging
import sys

import uvicorn

from .app import create_app
from .config import ConfigError, load
from .ledger import LedgerError


def main():
    ap = argparse.ArgumentParser(prog="hive_a2a", description="Serve a House persona over A2A.")
    ap.add_argument("--config", required=True, help="Path to the TOML config (see config.example.toml)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        app = create_app(load(args.config))
    except (ConfigError, LedgerError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    # TLS terminates in front of the server (Azure Container Apps ingress); trust its headers.
    uvicorn.run(app, host=args.host, port=args.port, proxy_headers=True, forwarded_allow_ips="*")
    return 0


if __name__ == "__main__":
    sys.exit(main())
