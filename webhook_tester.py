#!/usr/bin/env python3
"""
TradingView Webhook Tester & JSON Inspector (Free OSS Lite Edition)
Zero-dependency Python 3 local HTTP webhook receiver on 127.0.0.1:8787.

Features:
  - Validates incoming JSON alert payloads from TradingView / curl / ngrok
  - Extracts normalized trading signal fields (symbol, action, price, qty, strategy)
  - Optional shared secret/passphrase verification (--secret)
  - Reports exact parse & inspection latency in milliseconds
  - Optional JSONL webhook logging (--log-file)
  - Built-in end-to-end HTTP --self-test

License: MIT
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import time
from typing import Any
import urllib.error
import urllib.request

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
MAX_BODY_BYTES = 1_048_576  # 1 MiB


def _configure_stdio_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except OSError:
                pass


def _first_present(payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
    lowered = {str(k).lower(): v for k, v in payload.items()}
    for key in keys:
        if key in lowered and lowered[key] not in (None, ""):
            return lowered[key]
    return None


def inspect_tradingview_payload(
    raw_bytes: bytes,
    *,
    expected_secret: str | None = None,
    header_secret: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """
    Validate and parse a TradingView JSON webhook body, returning (http_status, response_dict).
    Measures exact inspection timing in milliseconds.
    """
    t0 = time.perf_counter()
    received_at = datetime.now(timezone.utc).isoformat()

    if not raw_bytes or not raw_bytes.strip():
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        return HTTPStatus.BAD_REQUEST, {
            "ok": False,
            "error": "Empty request body; expected JSON object.",
            "received_at": received_at,
            "latency_ms": elapsed_ms,
        }

    try:
        decoded = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        return HTTPStatus.BAD_REQUEST, {
            "ok": False,
            "error": f"Invalid UTF-8 body: {exc}",
            "received_at": received_at,
            "latency_ms": elapsed_ms,
        }

    try:
        data = json.loads(decoded)
    except json.JSONDecodeError as exc:
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        return HTTPStatus.BAD_REQUEST, {
            "ok": False,
            "error": f"Invalid JSON payload at line {exc.lineno} col {exc.colno}: {exc.msg}",
            "received_at": received_at,
            "latency_ms": elapsed_ms,
        }

    if not isinstance(data, dict):
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        return HTTPStatus.BAD_REQUEST, {
            "ok": False,
            "error": f"Expected JSON object ({{...}}), got {type(data).__name__}.",
            "received_at": received_at,
            "latency_ms": elapsed_ms,
        }

    # Optional secret verification
    payload_secret = _first_present(data, ("secret", "passphrase", "token", "api_key"))
    provided_secret = header_secret if header_secret else (str(payload_secret) if payload_secret is not None else None)
    if expected_secret is not None and provided_secret != expected_secret:
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        return HTTPStatus.UNAUTHORIZED, {
            "ok": False,
            "error": "Secret/passphrase mismatch.",
            "received_at": received_at,
            "latency_ms": elapsed_ms,
        }

    symbol = _first_present(data, ("symbol", "ticker", "pair", "market", "instrument"))
    action = _first_present(data, ("action", "side", "order_action", "signal", "direction"))
    price = _first_present(data, ("price", "close", "entry", "limit_price"))
    qty = _first_present(data, ("qty", "quantity", "contracts", "amount", "size", "risk_pct"))
    order_type = _first_present(data, ("order_type", "type"))
    timeframe = _first_present(data, ("timeframe", "interval", "tf"))
    exchange = _first_present(data, ("exchange", "broker"))
    strategy = _first_present(data, ("strategy", "alert_name", "name"))
    tv_time = _first_present(data, ("time", "timenow", "timestamp"))

    warnings: list[str] = []
    if symbol is None:
        warnings.append("Missing symbol/ticker field (e.g. 'ticker': '{{ticker}}').")
    if action is None:
        warnings.append("Missing action/side field (e.g. 'action': '{{strategy.order.action}}').")
    if price is None:
        warnings.append("No price/close field provided (optional for market orders).")

    parsed_signal = {
        "symbol": str(symbol).upper() if symbol is not None else None,
        "action": str(action).lower() if action is not None else None,
        "order_type": str(order_type).lower() if order_type is not None else "market",
        "price": price,
        "qty": qty,
        "exchange": exchange,
        "timeframe": timeframe,
        "strategy": strategy,
        "tv_time": tv_time,
    }

    signal_complete = symbol is not None and action is not None
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)

    return HTTPStatus.OK, {
        "ok": True,
        "valid_json": True,
        "signal_complete": signal_complete,
        "received_at": received_at,
        "latency_ms": elapsed_ms,
        "parsed_signal": parsed_signal,
        "warnings": warnings,
        "raw_keys": list(data.keys()),
        "raw_payload": data,
    }


class WebhookInspectorServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_cls: type[BaseHTTPRequestHandler],
        *,
        expected_secret: str | None = None,
        log_file: Path | None = None,
        quiet: bool = False,
        once: bool = False,
    ) -> None:
        self.expected_secret = expected_secret
        self.log_file = log_file
        self.quiet = quiet
        self.once = once
        self.started_at = time.monotonic()
        self.requests_count = 0
        self.lock = threading.Lock()
        super().__init__(server_address, handler_cls)


class WebhookRequestHandler(BaseHTTPRequestHandler):
    server: WebhookInspectorServer

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress default noisy BaseHTTPRequestHandler stderr logging
        return

    def _send_json(self, status: int, body: dict[str, Any]) -> None:
        encoded = json.dumps(body, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        uptime_s = round(time.monotonic() - self.server.started_at, 2)
        host, port = self.server.server_address[:2]
        self._send_json(
            HTTPStatus.OK,
            {
                "service": "tradingview-webhook-tester",
                "status": "listening",
                "endpoint": f"http://{host}:{port}/webhook",
                "uptime_sec": uptime_s,
                "webhooks_received": self.server.requests_count,
                "secret_required": self.server.expected_secret is not None,
            },
        )

    def do_POST(self) -> None:
        content_len_raw = self.headers.get("Content-Length", "0")
        try:
            content_len = int(content_len_raw)
        except ValueError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "Invalid Content-Length header"})
            return

        if content_len < 0 or content_len > MAX_BODY_BYTES:
            self._send_json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                {"ok": False, "error": f"Payload size {content_len} exceeds {MAX_BODY_BYTES} bytes limit"},
            )
            return

        raw_body = self.rfile.read(content_len)
        header_secret = self.headers.get("X-Webhook-Secret")
        status, result = inspect_tradingview_payload(
            raw_body,
            expected_secret=self.server.expected_secret,
            header_secret=header_secret,
        )

        with self.server.lock:
            self.server.requests_count += 1
            seq = self.server.requests_count
            if self.server.log_file is not None:
                self.server.log_file.parent.mkdir(parents=True, exist_ok=True)
                record = {"seq": seq, "path": self.path, "http_status": int(status), **result}
                with self.server.log_file.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")

        if not self.server.quiet:
            self._print_console_report(seq, int(status), result)

        # Strip raw_payload echo if huge? Keep concise response for caller
        response_body = {k: v for k, v in result.items() if k != "raw_payload"}
        self._send_json(int(status), response_body)

        if self.server.once:
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    def _print_console_report(self, seq: int, http_status: int, result: dict[str, Any]) -> None:
        client = self.client_address[0]
        print("-" * 64)
        print(
            f"[Webhook #{seq}] {result.get('received_at')} | {client} -> POST {self.path} "
            f"| HTTP {http_status} | {result.get('latency_ms')} ms"
        )
        if not result.get("ok"):
            print(f"  [ERROR] {result.get('error')}")
        else:
            sig = result["parsed_signal"]
            print(
                f"  Signal : symbol={sig['symbol']} | action={sig['action']} | "
                f"type={sig['order_type']} | price={sig['price']} | qty={sig['qty']}"
            )
            if sig["strategy"] or sig["timeframe"] or sig["exchange"]:
                print(
                    f"  Meta   : exchange={sig['exchange']} | tf={sig['timeframe']} | strategy={sig['strategy']}"
                )
            for warn in result.get("warnings", []):
                print(f"  [WARN] {warn}")
            print(f"  Raw    : {json.dumps(result.get('raw_payload'), ensure_ascii=False)}")
        sys.stdout.flush()


def _http_call(url: str, method: str = "GET", body: bytes | None = None, headers: dict[str, str] | None = None) -> tuple[int, dict[str, Any]]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


def run_self_test() -> int:
    """Spin up live local HTTP server on ephemeral port and verify all webhook cases."""
    print("[SELF-TEST] Running tradingview-webhook-tester verification suite...")
    failures: list[str] = []

    srv = WebhookInspectorServer(
        ("127.0.0.1", 0),
        WebhookRequestHandler,
        expected_secret="tv-pass-123",
        quiet=True,
    )
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"

    try:
        # 1. GET /health
        st1, body1 = _http_call(f"{base_url}/health")
        if st1 != 200 or body1.get("status") != "listening":
            failures.append(f"GET /health failed: {st1} {body1}")
        else:
            print(f"  [PASS] GET /health on 127.0.0.1:{port}")

        # 2. Valid TradingView JSON POST
        valid_payload = json.dumps(
            {
                "secret": "tv-pass-123",
                "ticker": "BTCUSDT.P",
                "action": "buy",
                "order_type": "market",
                "price": 94250.5,
                "contracts": 0.05,
                "timeframe": "15m",
                "exchange": "BYBIT",
                "strategy": "EMA Breakout v6",
            }
        ).encode("utf-8")
        st2, body2 = _http_call(
            f"{base_url}/webhook",
            method="POST",
            body=valid_payload,
            headers={"Content-Type": "application/json"},
        )
        sig2 = body2.get("parsed_signal", {})
        if (
            st2 != 200
            or not body2.get("ok")
            or not body2.get("signal_complete")
            or sig2.get("symbol") != "BTCUSDT.P"
            or sig2.get("action") != "buy"
            or body2.get("latency_ms", -1) < 0
        ):
            failures.append(f"Valid POST webhook failed: {st2} {body2}")
        else:
            print(f"  [PASS] Valid TradingView JSON parsed in {body2['latency_ms']} ms")

        # 3. Invalid JSON syntax -> 400
        st3, body3 = _http_call(
            f"{base_url}/webhook",
            method="POST",
            body=b"{bad json:",
            headers={"Content-Type": "application/json"},
        )
        if st3 != 400 or body3.get("ok") is not False:
            failures.append(f"Invalid JSON did not return 400: {st3} {body3}")
        else:
            print("  [PASS] Malformed JSON rejected with HTTP 400")

        # 4. Wrong secret -> 401
        bad_secret_payload = json.dumps({"secret": "wrong", "ticker": "ETHUSDT", "action": "sell"}).encode("utf-8")
        st4, body4 = _http_call(
            f"{base_url}/webhook",
            method="POST",
            body=bad_secret_payload,
            headers={"Content-Type": "application/json"},
        )
        if st4 != 401 or body4.get("ok") is not False:
            failures.append(f"Wrong secret did not return 401: {st4} {body4}")
        else:
            print("  [PASS] Secret mismatch rejected with HTTP 401")

        # 5. Incomplete TradingView payload -> 200 with warnings & signal_complete=False
        incomplete_payload = json.dumps({"secret": "tv-pass-123", "note": "ping"}).encode("utf-8")
        st5, body5 = _http_call(
            f"{base_url}/webhook",
            method="POST",
            body=incomplete_payload,
            headers={"Content-Type": "application/json"},
        )
        if st5 != 200 or body5.get("signal_complete") is not False or not body5.get("warnings"):
            failures.append(f"Incomplete payload check failed: {st5} {body5}")
        else:
            print("  [PASS] Incomplete JSON flagged with clear field warnings")

        # 6. Non-object JSON array -> 400
        st6, body6 = _http_call(
            f"{base_url}/webhook",
            method="POST",
            body=b"[1, 2, 3]",
            headers={"Content-Type": "application/json"},
        )
        if st6 != 400:
            failures.append(f"JSON array did not return 400: {st6} {body6}")
        else:
            print("  [PASS] Non-object JSON array rejected with HTTP 400")

    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=2)

    if failures:
        print("\n[SELF-TEST FAILED]")
        for err in failures:
            print(f"  - {err}")
        return 1

    print("\n[SELF-TEST PASSED] 100% PASS (all HTTP webhook inspector tests succeeded).")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="webhook_tester.py",
        description="Free Local TradingView JSON Webhook Inspector & Tester (default: 127.0.0.1:8787).",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Bind address (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Listen port (default: {DEFAULT_PORT})")
    parser.add_argument("--secret", default=None, help="Optional expected passphrase/secret or X-Webhook-Secret")
    parser.add_argument("--log-file", default=None, help="Optional JSONL file path to log received webhooks")
    parser.add_argument("--once", action="store_true", help="Exit automatically after receiving 1 POST webhook")
    parser.add_argument("--quiet", action="store_true", help="Minimal stdout output")
    parser.add_argument("--self-test", action="store_true", help="Run built-in HTTP self-tests and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdio_utf8()
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    if not (1 <= args.port <= 65535):
        print(f"[ERROR] Port must be between 1 and 65535, got {args.port}", file=sys.stderr)
        return 2

    log_path = Path(args.log_file) if args.log_file else None
    server = WebhookInspectorServer(
        (args.host, args.port),
        WebhookRequestHandler,
        expected_secret=args.secret,
        log_file=log_path,
        quiet=args.quiet,
        once=args.once,
    )

    print("=" * 64)
    print("  TradingView Webhook Tester (Free OSS Lite Edition)")
    print("=" * 64)
    print(f"Listening on : http://{args.host}:{args.port}/webhook")
    print(f"Health Check : http://{args.host}:{args.port}/health")
    if args.secret:
        print("Secret Check : ENABLED (checks payload 'secret'/'passphrase' or 'X-Webhook-Secret')")
    if log_path:
        print(f"JSONL Log    : {log_path}")
    print("\nTest with curl:")
    print(
        f'  curl -X POST http://{args.host}:{args.port}/webhook '
        '-H "Content-Type: application/json" '
        '-d "{\\"ticker\\":\\"BTCUSDT\\",\\"action\\":\\"buy\\",\\"price\\":95000,\\"qty\\":0.02}"'
    )
    print("\nPress Ctrl+C to stop.")
    print("=" * 64)
    sys.stdout.flush()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[STOP] Shutting down webhook tester...")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
