#!/usr/bin/env python3
"""Network utilities for start.sh.

Subcommands:
  parse-dsn <url>               Print host and port (one per line).
  tcp-probe <host> <port>       Exit 0 if reachable, 1 otherwise.
  http-probe <url> [status]     Exit 0 if HTTP status matches (default 200).
                                Prints error message on failure.
  llm-probe <base_url>          Exit 0 when LLM endpoint is up.
                                Prints the responding URL on success.
"""

import socket
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit


def cmd_parse_dsn(args):
    dsn = args[0].strip()
    parts = urlsplit(dsn)
    print(parts.hostname or "")
    print(parts.port or 5432)


def cmd_tcp_probe(args):
    host, port = args[0], int(args[1])
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        sys.exit(0 if sock.connect_ex((host, port)) == 0 else 1)


def cmd_http_probe(args):
    url = args[0]
    expected = int(args[1]) if len(args) > 1 else 200
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            status = response.status
    except urllib.error.HTTPError as e:
        status = e.code
    except Exception as e:
        print(str(e))
        sys.exit(1)
    if status != expected:
        print(f"HTTP {status}")
        sys.exit(1)


def cmd_llm_probe(args):
    base_url = args[0].strip().rstrip("/")
    parsed = urlsplit(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port
    scheme = parsed.scheme or "http"
    root = f"{scheme}://{host}:{port}" if port else f"{scheme}://{host}"
    candidates = [
        f"{root}/health", f"{root}/v1/models",
        f"{base_url}/health", f"{base_url}/v1/models",
    ]
    seen: set[str] = set()
    for url in candidates:
        if not url or url in seen:
            continue
        seen.add(url)
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, method="GET"), timeout=2
            ) as r:
                status = int(getattr(r, "status", 0) or 0)
            if 200 <= status < 500:
                print(url)
                sys.exit(0)
            print(f"{url} -> HTTP {status}")
        except urllib.error.HTTPError as e:
            if 200 <= int(e.code) < 500:
                print(url)
                sys.exit(0)
            print(f"{url} -> HTTP {e.code}")
        except Exception as e:
            print(f"{url} -> {e}")
    sys.exit(1)


COMMANDS = {
    "parse-dsn": cmd_parse_dsn,
    "tcp-probe": cmd_tcp_probe,
    "http-probe": cmd_http_probe,
    "llm-probe": cmd_llm_probe,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"Usage: {sys.argv[0]} <subcommand> [args...]", file=sys.stderr)
        print(f"Subcommands: {', '.join(COMMANDS)}", file=sys.stderr)
        sys.exit(2)
    COMMANDS[sys.argv[1]](sys.argv[2:])
