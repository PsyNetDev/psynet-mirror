from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).parents[1].parent
    / ".cursor"
    / "skills"
    / "experiment"
    / "public-tunnel"
    / "scripts"
    / "public_tunnel.py"
)


def load_public_tunnel_module():
    spec = importlib.util.spec_from_file_location("public_tunnel", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_public_tunnel_prefers_cloudflared(monkeypatch) -> None:
    module = load_public_tunnel_module()

    monkeypatch.setattr(
        module.shutil,
        "which",
        lambda command: "/usr/bin/cloudflared" if command == "cloudflared" else None,
    )

    tunnel = module.PublicTunnel(5000)

    assert tunnel.command == [
        "/usr/bin/cloudflared",
        "tunnel",
        "--url",
        "http://127.0.0.1:5000",
    ]


def test_public_tunnel_downloads_cloudflared(monkeypatch, tmp_path: Path) -> None:
    module = load_public_tunnel_module()
    cached_binary = tmp_path / "cloudflared"
    commands = []

    monkeypatch.setattr(module, "CLOUDFLARED_CACHE", cached_binary)
    monkeypatch.setattr(module.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(module.shutil, "which", lambda command: None)
    monkeypatch.setattr(module, "command_available", lambda command: command == "curl")

    def fake_run_quietly(command, timeout=15):
        commands.append(command)
        cached_binary.write_text("#!/bin/sh\n")
        return module.subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(module, "run_quietly", fake_run_quietly)

    assert module.resolve_cloudflared_command() == str(cached_binary)
    assert cached_binary.exists()
    assert commands[0][-1].endswith("cloudflared-linux-amd64")


def test_public_tunnel_falls_back_to_localtunnel(monkeypatch) -> None:
    module = load_public_tunnel_module()

    monkeypatch.setattr(module, "resolve_cloudflared_command", lambda: None)
    monkeypatch.setattr(
        module, "command_available", lambda command: command == "localtunnel"
    )

    tunnel = module.PublicTunnel(5000)

    assert tunnel.command == [
        "localtunnel",
        "--port",
        "5000",
        "--local-host",
        "127.0.0.1",
    ]


def test_public_tunnel_supports_custom_local_host(monkeypatch) -> None:
    module = load_public_tunnel_module()

    monkeypatch.setattr(module, "resolve_cloudflared_command", lambda: None)
    monkeypatch.setattr(module, "command_available", lambda command: command == "npx")

    tunnel = module.PublicTunnel(1313, local_host="localhost")

    assert tunnel.command == [
        "npx",
        "-y",
        "localtunnel",
        "--port",
        "1313",
        "--local-host",
        "localhost",
    ]


def test_public_tunnel_filters_supported_urls() -> None:
    module = load_public_tunnel_module()

    assert module.is_public_tunnel_url(
        "https://northern-ordering-instant-thrown.trycloudflare.com"
    )
    assert module.is_public_tunnel_url("https://puny-ends-allow.loca.lt")
    assert not module.is_public_tunnel_url("https://www.cloudflare.com/website-terms/")
    assert not module.is_public_tunnel_url("http://127.0.0.1:5000/dashboard")
    assert not module.is_public_tunnel_url("https://[config.yml")


def test_public_tunnel_rewrites_local_urls() -> None:
    module = load_public_tunnel_module()

    public_url = module.to_public_url(
        "http://127.0.0.1:5000/ad?assignmentId=A1&workerId=W1",
        "https://example.trycloudflare.com",
    )
    dashboard_url = module.to_public_url(
        "http://127.0.0.1:5000/dashboard/develop",
        "https://example.trycloudflare.com",
        username="admin",
        password="p@ ss",
    )

    assert (
        public_url == "https://example.trycloudflare.com/ad?assignmentId=A1&workerId=W1"
    )
    assert (
        dashboard_url
        == "https://admin:p%40%20ss@example.trycloudflare.com/dashboard/develop"
    )


def test_public_tunnel_accepts_handoff_object() -> None:
    module = load_public_tunnel_module()
    events = []

    class Handoff:
        def set_public_tunnel_url(self, url: str) -> None:
            events.append(("url", url))

        def maybe_print(self) -> None:
            events.append(("print", None))

    callback = module.coerce_url_callback(Handoff())
    assert callback is not None

    callback("https://example.trycloudflare.com")

    assert events == [
        ("url", "https://example.trycloudflare.com"),
        ("print", None),
    ]


def test_public_tunnel_print_command(monkeypatch, capsys) -> None:
    module = load_public_tunnel_module()

    monkeypatch.setattr(
        module, "resolve_cloudflared_command", lambda: "/tmp/cloudflared"
    )

    assert module.main(["--port", "1313", "--print-command"]) == 0
    output = capsys.readouterr().out
    assert output.strip() == "/tmp/cloudflared tunnel --url http://127.0.0.1:1313"
