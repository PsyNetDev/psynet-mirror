#!/usr/bin/env python3
"""Expose a local HTTP service through an ephemeral public tunnel."""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Protocol, Sequence
from urllib.parse import quote, urlsplit, urlunsplit

URL_PATTERN = re.compile(r"https?://[^\s'\")<>]+")
CLOUDFLARED_DOWNLOADS = {
    "aarch64": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64",
    "arm64": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64",
    "amd64": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
    "x86_64": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
}
CLOUDFLARED_CACHE = Path("/tmp/cloudflared")


class TunnelHandoff(Protocol):
    """Callback-compatible object used by caller-specific handoff code."""

    def set_public_tunnel_url(self, url: str) -> None:
        """Record a public tunnel URL."""

    def maybe_print(self) -> None:
        """Print caller-specific handoff details when ready."""


UrlCallback = Callable[[str], None]


class PublicTunnel:
    """Manage a public tunnel subprocess for a local HTTP server."""

    def __init__(
        self,
        port: int,
        on_public_url: UrlCallback | TunnelHandoff | None = None,
        *,
        local_host: str = "127.0.0.1",
    ) -> None:
        self.port = port
        self.local_host = local_host
        self.on_public_url = coerce_url_callback(on_public_url)
        self.process: subprocess.Popen[str] | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the tunnel if supported tooling is available."""

        command = self.command
        if command is None:
            print(
                "Public tunnel skipped: install cloudflared, curl, localtunnel, or npx.",
                file=sys.stderr,
            )
            return

        print(f"Starting public tunnel: {' '.join(command)}")
        self.process = subprocess.Popen(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )
        self.thread = threading.Thread(target=self._stream_output, daemon=True)
        self.thread.start()

    def wait(self) -> int:
        """Wait for the tunnel subprocess to exit."""

        if self.process is None:
            return 2
        return self.process.wait()

    def stop(self) -> None:
        """Stop the tunnel subprocess."""

        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()

    @property
    def command(self) -> list[str] | None:
        """Return the public tunnel command to run."""

        cloudflared = resolve_cloudflared_command()
        if cloudflared is not None:
            return [
                cloudflared,
                "tunnel",
                "--url",
                f"http://{self.local_host}:{self.port}",
            ]

        if command_available("localtunnel"):
            return [
                "localtunnel",
                "--port",
                str(self.port),
                "--local-host",
                self.local_host,
            ]
        if command_available("npx"):
            return [
                "npx",
                "-y",
                "localtunnel",
                "--port",
                str(self.port),
                "--local-host",
                self.local_host,
            ]
        return None

    def _stream_output(self) -> None:
        """Relay tunnel output and capture its public URL."""

        if self.process is None or self.process.stdout is None:
            return
        for line in self.process.stdout:
            print(line, end="")
            for url in URL_PATTERN.findall(line):
                cleaned = url.rstrip(".,;")
                if is_public_tunnel_url(cleaned):
                    if self.on_public_url is not None:
                        self.on_public_url(cleaned)
                    else:
                        print_public_tunnel_handoff(cleaned)


def coerce_url_callback(
    callback_or_handoff: UrlCallback | TunnelHandoff | None,
) -> UrlCallback | None:
    """Return a URL callback from either a function or handoff object."""

    if callback_or_handoff is None:
        return None
    if callable(callback_or_handoff):
        return callback_or_handoff

    def callback(url: str) -> None:
        callback_or_handoff.set_public_tunnel_url(url)
        callback_or_handoff.maybe_print()

    return callback


def command_available(command: str) -> bool:
    """Return whether a command exists on PATH."""

    return shutil.which(command) is not None


def resolve_cloudflared_command() -> str | None:
    """Return a cloudflared executable, downloading a temporary copy if needed."""

    discovered = shutil.which("cloudflared")
    if discovered:
        return discovered

    if CLOUDFLARED_CACHE.exists() and os.access(CLOUDFLARED_CACHE, os.X_OK):
        return str(CLOUDFLARED_CACHE)

    if not command_available("curl"):
        return None

    url = CLOUDFLARED_DOWNLOADS.get(platform.machine().lower())
    if url is None:
        return None

    print(f"Downloading cloudflared quick-tunnel binary to {CLOUDFLARED_CACHE}...")
    download = run_quietly(
        [
            "curl",
            "-L",
            "--fail",
            "--retry",
            "3",
            "--retry-delay",
            "2",
            "-o",
            str(CLOUDFLARED_CACHE),
            url,
        ],
        timeout=120,
    )
    if download.returncode != 0:
        print(
            "cloudflared download failed; falling back to localtunnel if available.",
            file=sys.stderr,
        )
        return None

    CLOUDFLARED_CACHE.chmod(0o755)
    return str(CLOUDFLARED_CACHE)


def strip_userinfo(url: str) -> str:
    """Remove embedded credentials from a URL."""

    parsed = urlsplit(url)
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit(
        (parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
    )


def with_path(url: str, path: str) -> str:
    """Return a copy of a URL with a different path and no query."""

    parsed = urlsplit(strip_userinfo(url))
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def is_local_url(url: str) -> bool:
    """Return whether a URL points at a local development server."""

    parsed = urlsplit(url)
    return parsed.hostname in {"127.0.0.1", "localhost", "0.0.0.0"}


def is_public_tunnel_url(url: str) -> bool:
    """Return whether a URL is from a supported public tunnel provider."""

    try:
        hostname = urlsplit(url).hostname or ""
    except ValueError:
        return False
    return hostname.endswith(".trycloudflare.com") or hostname.endswith(".loca.lt")


def to_public_url(
    local_url: str,
    public_base_url: str,
    username: str | None = None,
    password: str | None = None,
) -> str:
    """Map a local URL to the public tunnel host."""

    local = urlsplit(strip_userinfo(local_url))
    public = urlsplit(public_base_url)
    netloc = public.netloc
    if username is not None and password is not None:
        netloc = f"{quote(username, safe='')}:{quote(password, safe='')}@{netloc}"
    return urlunsplit((public.scheme, netloc, local.path, local.query, local.fragment))


def run_quietly(
    command: Sequence[str], timeout: int = 15
) -> subprocess.CompletedProcess[str]:
    """Run a short command without raising on non-zero exit."""

    try:
        return subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        return subprocess.CompletedProcess(command, 127, "", str(error))


def print_public_tunnel_handoff(url: str) -> None:
    """Print the generic public tunnel handoff block."""

    print("\n=== Public tunnel ready ===")
    print(f"Public URL: {url}")
    print("This URL is temporary and expires when the tunnel process stops.")
    print("=== End public tunnel ready ===\n", flush=True)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""

    parser = argparse.ArgumentParser(
        description="Expose a local HTTP service through a temporary public tunnel.",
    )
    parser.add_argument(
        "--port",
        type=int,
        required=True,
        help="Local HTTP port to expose.",
    )
    parser.add_argument(
        "--local-host",
        default="127.0.0.1",
        help="Local host to expose. Defaults to 127.0.0.1.",
    )
    parser.add_argument(
        "--print-command",
        action="store_true",
        help="Print the selected tunnel command without starting it.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""

    parser = build_parser()
    args = parser.parse_args(argv)
    tunnel = PublicTunnel(args.port, local_host=args.local_host)
    if args.print_command:
        command = tunnel.command
        if command is None:
            print("No supported public tunnel command is available.", file=sys.stderr)
            return 2
        print(" ".join(command))
        return 0

    tunnel.start()
    if tunnel.process is None:
        return 2
    try:
        return tunnel.wait()
    except KeyboardInterrupt:
        tunnel.stop()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
