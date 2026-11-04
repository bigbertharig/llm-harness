"""Focused Responses API tool-call diagnostic for the local rig."""
import json
import sys
import urllib.request

payload = {
    "model": "gpu-rig/coder-30b",
    "input": "Call the read_marker function with {} now. Do not answer from memory.",
    "tools": [{
        "type": "function",
        "name": "read_marker",
        "description": "Read the test receipt marker. Call with an empty object.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "strict": True,
    }],
    "tool_choice": "auto" if "--auto" in sys.argv else "required",
    "max_output_tokens": 256,
}
req = urllib.request.Request(
    "http://127.0.0.1:8080/v1/responses",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json", "X-Require-Ready": "true"},
)
with urllib.request.urlopen(req, timeout=90) as response:
    result = json.load(response)
print(json.dumps({"status": result.get("status"), "output": result.get("output"),
                  "usage": result.get("usage"), "error": result.get("error")}, indent=2))
