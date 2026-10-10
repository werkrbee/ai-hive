"""Run the A2A TCK against hive_a2a locally, with the stub model and real auth.

The TCK has no way to send credentials, and the server refuses every request without
them. So this starts the server behind a local proxy that adds a token signed by a
throwaway key the server is configured to trust. Auth stays on; nothing is turned off
for the run.

  python conformance/run.py --tck /path/to/a2a-tck --tck-python /path/to/tck/venv/bin/python

Reports land in the TCK's reports/ directory. Copy compatibility.json next to this file
to record a run.
"""
import argparse
import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import jwt
import uvicorn
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from hive_a2a.app import create_app  # noqa: E402
from hive_a2a.config import load  # noqa: E402

PROXY, SERVER = 9999, 9998
ISSUER, AUDIENCE, CLIENT = "https://login.conformance.test/v2.0", "conformance-api", "conformance-client"


def config_for(root, key):
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    (root / "jwks.json").write_text(json.dumps({"keys": [{**jwk, "kid": "c1", "use": "sig", "alg": "RS256"}]}))
    (root / "config.toml").write_text(f"""
[server]
persona = "patricia"
capability = "governance-review"
public_url = "http://localhost:{PROXY}/"
database = "data/tasks.db"
ledger = "data/ledger.jsonl"
prompt_files = ["hives/rules-hive/rules/queen-charter/AGENTS.md"]

[auth]
issuer = "{ISSUER}"
audience = "{AUDIENCE}"
jwks_path = "jwks.json"
token_url = "https://login.conformance.test/token"
scope = "api://conformance-api/.default"
allowed_clients = ["{CLIENT}"]

[model]
provider = "stub"
name = "stub"
input_usd_per_mtok = 0.0
output_usd_per_mtok = 0.0
""")
    return load(root / "config.toml")


def proxy(key):
    client = httpx.AsyncClient(base_url=f"http://127.0.0.1:{SERVER}", timeout=60)

    async def forward(request):
        token = jwt.encode({"iss": ISSUER, "aud": AUDIENCE, "azp": CLIENT, "exp": int(time.time()) + 600},
                           key, algorithm="RS256", headers={"kid": "c1"})
        headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}
        headers["authorization"] = f"Bearer {token}"
        upstream = await client.request(request.method, request.url.path, params=request.query_params,
                                        content=await request.body(), headers=headers)
        drop = {"content-length", "transfer-encoding", "connection", "content-encoding"}
        return Response(upstream.content, upstream.status_code,
                        {k: v for k, v in upstream.headers.items() if k.lower() not in drop})

    return Starlette(routes=[Route("/{path:path}", forward, methods=["GET", "POST", "HEAD"])])


def serve(app, port):
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            return server
        time.sleep(0.1)
    raise RuntimeError(f"nothing started on port {port}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tck", required=True, type=Path, help="a2a-tck checkout")
    ap.add_argument("--tck-python", default=sys.executable, help="Python with the TCK installed")
    ap.add_argument("tck_args", nargs="*", help="extra run_tck.py arguments, after --")
    args = ap.parse_args()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with tempfile.TemporaryDirectory() as tmp:
        servers = [serve(create_app(config_for(Path(tmp), key)), SERVER), serve(proxy(key), PROXY)]
        try:
            run = subprocess.run([args.tck_python, "run_tck.py", "--sut-host", f"http://localhost:{PROXY}",
                                  "--transport", "jsonrpc", *args.tck_args], cwd=args.tck)
        finally:
            for s in servers:
                s.should_exit = True
            time.sleep(0.5)
    return run.returncode


if __name__ == "__main__":
    sys.exit(main())
