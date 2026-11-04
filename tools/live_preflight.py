"""Live, non-loading gateway preflight for a prepared harness route.

Run on the Pi after gateway/orchestration have prepared the model. Writes a JSON receipt.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ready_roster import fetch_ready_roster


def call(base: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    headers = {"Accept": "application/json"}
    if body is not None:
        headers.update({"Content-Type": "application/json", "X-Require-Ready": "true"})
    key = os.environ.get("LLM_GATEWAY_API_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = Request(base.rstrip("/") + path, headers=headers,
                  data=json.dumps(body).encode() if body is not None else None)
    try:
        with urlopen(req, timeout=120) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        return exc.code, json.load(exc)


def profile_signature(status: dict) -> list[tuple]:
    return sorted((p.get("id"), p.get("model"), p.get("port"), p.get("ctx_size"), p.get("lease"))
                  for p in status.get("profiles", []))


def run(base: str, route_id: str, expected_model: str) -> dict:
    roster = fetch_ready_roster(base, os.environ.get("LLM_GATEWAY_API_KEY"))
    route = next((r for r in roster["data"] if r["id"] == route_id), None)
    if route is None or route["model"] != expected_model:
        raise ValueError(f"expected ready route {route_id} for {expected_model}; got {route}")
    status_code, before = call(base, "/v1/rig/status")
    if status_code != 200:
        raise RuntimeError(f"rig status returned {status_code}")
    token_count = None
    tokenizer_check = "unavailable"
    if route.get("tokenizer_path"):
        token_status, tokens = call(base, route["tokenizer_path"],
                                    {"model": route_id, "content": "ready roster preflight"})
        if token_status != 200 or not isinstance(tokens.get("tokens"), list):
            raise RuntimeError(f"ready-only tokenize returned {token_status}: {tokens}")
        token_count = len(tokens["tokens"])
        tokenizer_check = "passed"
    chat_status, chat = call(base, "/v1/chat/completions", {
        "model": route_id, "messages": [{"role": "user", "content": "Reply with one short word."}],
        "max_tokens": 48, "temperature": 0,
    })
    if chat_status != 200 or not chat.get("choices"):
        raise RuntimeError(f"ready-only chat returned {chat_status}: {chat}")
    choice = chat["choices"][0]
    answer = choice.get("message", {}).get("content") or ""
    if not answer.strip():
        raise RuntimeError("ready-only chat returned no visible answer")
    offered_status, offered = call(base, "/v1/models")
    if offered_status != 200:
        raise RuntimeError(f"models returned {offered_status}")
    cold = next((m["id"] for m in offered["data"]
                 if m["id"] not in {r["id"] for r in roster["data"]}), None)
    if cold is None:
        raise RuntimeError("no cold published route available for admission test")
    cold_status, cold_reply = call(base, "/v1/chat/completions", {
        "model": cold, "messages": [{"role": "user", "content": "Do not load this model."}],
        "max_tokens": 8,
    })
    if cold_status != 409 or cold_reply.get("error", {}).get("type") != "model_not_ready":
        raise RuntimeError(f"cold route admission returned {cold_status}: {cold_reply}")
    after_status, after = call(base, "/v1/rig/status")
    if after_status != 200 or profile_signature(before) != profile_signature(after):
        raise RuntimeError("loaded rig profile changed during preflight")
    return {
        "route": route, "cold_route": cold, "token_count": token_count,
        "tokenizer_check": tokenizer_check,
        "chat_answer": answer[:200], "finish_reason": choice.get("finish_reason"),
        "cold_status": cold_status, "profiles_before": profile_signature(before),
        "profiles_after": profile_signature(after), "passed": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway", default="http://127.0.0.1:8080")
    parser.add_argument("--route", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    receipt = {"at": dt.datetime.now(dt.timezone.utc).isoformat(), "gateway": args.gateway,
               "expected_route": args.route, "expected_model": args.model}
    try:
        receipt.update(run(args.gateway, args.route, args.model))
    except Exception as exc:
        receipt.update({"passed": False, "error": str(exc)})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
