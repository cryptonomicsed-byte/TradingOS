"""Contract test: Vantage's real backend/quant_client.py against the real Julia server.

Starts `src/server.jl` on an ephemeral 127.0.0.1 port (QUANT_JULIA_ENABLED=1 in
the *child* env only), points quant_client at it via QUANT_JULIA_URL, and checks
that status() and backtest() parse the live responses. Vantage is imported
read-only from VANTAGE_ROOT (or PYTHONPATH); nothing in Vantage is modified.

    PYTHONPATH=/path/to/Vantage /opt/ares/venv/bin/python -m pytest -q test/contract
"""
import asyncio
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]  # .../TradingOSQuant
if os.environ.get("VANTAGE_ROOT"):
    sys.path.insert(0, os.environ["VANTAGE_ROOT"])

qc = pytest.importorskip("backend.quant_client")
JULIA = os.environ.get("JULIA") or shutil.which("julia")
if not JULIA:
    pytest.skip("julia not on PATH", allow_module_level=True)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    port = _free_port()
    env = {**os.environ, "QUANT_JULIA_ENABLED": "1", "JULIA_HOST": "127.0.0.1", "JULIA_PORT": str(port)}
    proc = subprocess.Popen([JULIA, "--project=.", "src/server.jl"], cwd=PKG, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    deadline = time.time() + float(os.environ.get("QUANT_JULIA_START_TIMEOUT", "300"))
    try:
        while True:
            if proc.poll() is not None:
                raise RuntimeError("julia server exited: " + proc.stdout.read().decode(errors="replace"))
            try:
                with urllib.request.urlopen(url + "/health", timeout=2) as r:
                    if r.status == 200:
                        break
            except OSError:
                pass
            if time.time() > deadline:
                raise RuntimeError("julia server did not come up")
            time.sleep(1)
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()


def _candles(n=300):
    # deterministic regime-switching series (no RNG): up 75 bars, down 75 bars, ...
    out, px = [], 100.0
    for i in range(n):
        step = (0.8 if (i // 75) % 2 == 0 else -0.8) + 0.5 * math.sin(i * 0.7)
        o, px = px, max(1.0, px + step)
        out.append({"time": 1_700_000_000 + i * 86400, "open": o, "high": max(o, px) + 0.4,
                    "low": min(o, px) - 0.4, "close": px, "volume": 1000.0 + (i % 7) * 50})
    return out


@pytest.fixture
def client_env(server, monkeypatch):
    monkeypatch.setenv("QUANT_JULIA_ENABLED", "1")
    monkeypatch.setenv("QUANT_JULIA_URL", server)
    qc._cache.clear()
    yield
    qc._cache.clear()


def test_status_against_live_server(client_env):
    s = asyncio.run(qc.status())
    assert s["quant_enabled"] is True and s["quant_ok"] is True
    assert s["quant_health"]["status"] == "ok" and s["quant_health"]["service"] == "julia-quant"


def test_backtest_against_live_server(client_env, server):
    candles = _candles()
    r = asyncio.run(qc.backtest("btc", candles, {"hma_len": 21, "mom_req": 2, "vol_req": 0, "min_adx": 10}))
    assert r["ok"] is True, r
    assert r["engine"] == "TradingOSQuant (Julia)" and r["symbol"] == "BTC" and r["bars"] == 300
    m = r["metrics"]
    assert set(m) == set(qc._RESULT_KEYS)
    assert all(m[k] is not None for k in ("sharpe_ratio", "max_drawdown_pct", "win_rate", "total_trades",
                                           "net_profit", "net_profit_pct"))
    assert isinstance(m["total_trades"], int) and m["total_trades"] > 0
    assert m["total_trades"] == m["winning_trades"] + m["losing_trades"]
    assert 0.0 <= m["win_rate"] <= 1.0 and 0.0 <= m["max_drawdown_pct"] < 100.0
    # The same body sent raw must give identical numbers (determinism) and extras.
    body = qc.candles_to_body("btc", candles, qc.clean_params({"hma_len": 21, "mom_req": 2, "vol_req": 0,
                                                               "min_adx": 10}))
    req = urllib.request.Request(server + "/backtest", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = json.loads(resp.read())
    assert {k: raw[k] for k in qc._RESULT_KEYS} == m
    assert len(raw["equity_curve"]) == 300 and len(raw["trades"]) == m["total_trades"]
    assert math.isclose(raw["final_equity"], 10_000.0 + m["net_profit"], rel_tol=1e-9)


def test_service_side_rejection_is_fail_open(client_env, server, monkeypatch):
    # bypass the client-side MIN_BARS guard to hit the server's own 400 path
    monkeypatch.setattr(qc, "MIN_BARS", 10)
    r = asyncio.run(qc.backtest("eth", _candles(20)))
    assert r["ok"] is False and "HTTP 400" in r["error"]
