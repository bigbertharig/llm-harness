"""Read the gateway's prepared model roster without invoking model inference or loading."""

from __future__ import annotations

import argparse
import json
import os
from urllib.request import Request, urlopen


def fetch_ready_roster(base_url: str, api_key: str | None = None) -> dict:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(base_url.rstrip("/") + "/v1/rig/ready-roster", headers=headers)
    with urlopen(request, timeout=10) as response:
        roster = json.load(response)
    if (not isinstance(roster, dict) or roster.get("object") != "ready_roster"
            or roster.get("version") != 1 or not isinstance(roster.get("data"), list)):
        raise ValueError("gateway returned an unsupported ready-roster contract")
    for route in roster["data"]:
        if (not isinstance(route, dict) or not isinstance(route.get("id"), str)
                or not isinstance(route.get("model"), str) or route.get("state") != "ready"
                or not isinstance(route.get("context_length"), int)
                or route["context_length"] <= 0):
            raise ValueError("gateway returned an invalid ready route")
    return roster


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway", default="http://127.0.0.1:8080")
    args = parser.parse_args()
    roster = fetch_ready_roster(args.gateway, os.environ.get("LLM_GATEWAY_API_KEY"))
    print(json.dumps(roster, indent=2))


if __name__ == "__main__":
    main()
