# SearXNG MCP server

This folder is a standalone stdio MCP server. It requires Python 3 and a SearXNG instance that enables JSON search. It has no imports from `llm-harness`, `llm-gateway`, or `llm_orchestration`.

It lives in `llm-harness` because that repository owns model-facing tools and agent behavior. `llm-gateway` only routes model requests and manages rig readiness. The server itself remains copyable into another repository or host without the harness test runner.

Set `SEARXNG_URL` to the instance root or `/search` endpoint, then register this command in any MCP-capable harness:

```text
python3 /path/to/server.py
```

The server exposes `search_web({"query":"...","max_results":5})`. It returns up to ten distinct URLs with titles, short snippets, backend latency, and rate-limit information. The model chooses the query and which results to use. The server handles the HTTP request and result normalization.

For tests and the six-harness comparison runner, see `../../docs/research/searxng_mcp.md` in the source checkout. This folder can be copied independently; only `server.py` is required at runtime.
