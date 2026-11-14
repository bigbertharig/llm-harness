"""Bounded public HTTPS page reader for CPU-side source verification."""

import http.client
from html.parser import HTMLParser
import ipaddress
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit


MAX_BYTES = 1_000_000
MAX_REDIRECTS = 3
SKIP_TAGS = {"script", "style", "nav", "footer", "header", "aside"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.title = False
        self.title_parts = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self.skip += 1
        elif tag == "title":
            self.title = True
        elif tag in {"p", "br", "li", "div", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS and self.skip:
            self.skip -= 1
        elif tag == "title":
            self.title = False

    def handle_data(self, data):
        if self.title:
            self.title_parts.append(data)
        elif not self.skip:
            self.parts.append(data)


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(host, port=443, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address, 443), self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


def _public_address(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or
            parsed.password or parsed.port not in (None, 443) or
            "." not in parsed.hostname or parsed.hostname.endswith(".local")):
        raise ValueError("only public HTTPS URLs on port 443 are supported")
    addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)}
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("URL resolves outside the public internet")
    return parsed, sorted(addresses)[0]


def fetch_page(url, max_chars=12000, timeout=12):
    """Fetch one selected page on CPU; validate each redirect and pin DNS."""
    started = time.monotonic()
    current = url
    for redirect in range(MAX_REDIRECTS + 1):
        parsed, address = _public_address(current)
        connection = _PinnedHTTPS(parsed.hostname, address, timeout)
        try:
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            connection.request("GET", path, headers={"User-Agent": "rig-search/0.3 page reader",
                                                       "Accept": "text/html,application/xhtml+xml"})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location or redirect == MAX_REDIRECTS:
                    raise ValueError("redirect limit or missing Location")
                current = urljoin(current, location)
                continue
            content_type = response.getheader("Content-Type", "").lower()
            if response.status != 200 or not (content_type.startswith("text/html") or
                                                  content_type.startswith("application/xhtml+xml")):
                raise ValueError(f"unsupported page response: HTTP {response.status}")
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise ValueError("page exceeds size limit")
            charset = response.headers.get_content_charset() or "utf-8"
            page = _Text()
            page.feed(body.decode(charset, errors="replace"))
            text = "\n".join(" ".join(part.split()) for part in "".join(page.parts).splitlines() if part.strip())
            return {"url": current, "title": " ".join("".join(page.title_parts).split()),
                    "text": text[:max_chars], "chars_fetched": min(len(text), max_chars),
                    "truncated": len(text) > max_chars, "content_type": content_type,
                    "executor": "pi_cpu", "elapsed_seconds": round(time.monotonic() - started, 3)}
        finally:
            connection.close()
    raise ValueError("redirect limit")
