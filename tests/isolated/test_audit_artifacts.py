from pathlib import Path

from psynet.audit.artifacts import (
    HASHED_ARTIFACTS_DIR,
    sanitize_html_artifact,
    write_hashed_artifact,
)


def test_write_hashed_artifact_redacts_py_credentials(tmp_path: Path) -> None:
    source = tmp_path / "helper.py"
    source.write_text(
        "AWS_SECRET_ACCESS_KEY=secret\n"
        "PROLIFIC_API_TOKEN=token\n"
        'Username = "participant"\n',
        encoding="utf-8",
    )
    target_root = tmp_path / HASHED_ARTIFACTS_DIR

    url = write_hashed_artifact(source, target_root, HASHED_ARTIFACTS_DIR)

    prefix = f"{HASHED_ARTIFACTS_DIR}/"
    exported = target_root / url.removeprefix(prefix)
    assert exported.exists()
    assert exported.read_text(encoding="utf-8") == (
        "AWS_SECRET_ACCESS_KEY=[REDACTED]\n"
        "PROLIFIC_API_TOKEN=[REDACTED]\n"
        'Username = "participant"\n'
    )


def test_monitor_static_href_prefix_matches_blob_layout() -> None:
    from psynet.audit.artifacts import monitor_static_href_prefix

    assert monitor_static_href_prefix() == "../../../../monitor-static/"


def test_sanitize_html_artifact_ignores_binary_content(tmp_path: Path) -> None:
    source = tmp_path / "monitor.html"
    source.write_bytes(b"\xff\xfe not utf-8")

    sanitize_html_artifact(source)

    assert source.read_bytes() == b"\xff\xfe not utf-8"


def test_write_hashed_artifact_redacts_text_and_normalizes_legacy_prefix(
    tmp_path: Path,
) -> None:
    source = tmp_path / "psynet_debug.log"
    source.write_text(
        "Dashboard user: admin password: local-password\n"
        "AWS_SECRET_ACCESS_KEY=secret\n",
        encoding="utf-8",
    )
    target_root = tmp_path / HASHED_ARTIFACTS_DIR

    url = write_hashed_artifact(
        source,
        target_root,
        "https://example.test/artifacts/challenges",
    )

    prefix = f"https://example.test/{HASHED_ARTIFACTS_DIR}/"
    assert url.startswith(prefix)
    exported = target_root / url.removeprefix(prefix)
    assert exported.exists()
    assert exported.read_text(encoding="utf-8") == (
        "Dashboard user: admin password: [REDACTED]\nAWS_SECRET_ACCESS_KEY=[REDACTED]\n"
    )


def test_sanitize_html_artifact_rewrites_monitor_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "monitor.html"
    source.write_text(
        '<!doctype html><html><head><link href="/static/css/dashboard.css"></head>'
        '<body><a href="/dashboard/index">Dashboard</a>'
        '<script src="/static/vis@4.17.0/dist/vis.min.js"></script>'
        '<script src="/static/scripts/network-monitor.js"></script></body></html>',
        encoding="utf-8",
    )

    sanitize_html_artifact(source)

    html = source.read_text(encoding="utf-8")
    assert '<base href="./">' in html
    assert 'href="./static/css/dashboard.css"' in html
    assert 'href="#"' in html
    assert 'src="../../../../monitor-static/vis@4.17.0/dist/vis.min.js"' in html

    network_monitor = tmp_path / "static/scripts/network-monitor.js"
    assert network_monitor.exists()
    assert "Live dashboard node details are unavailable" in network_monitor.read_text(
        encoding="utf-8",
    )


def test_contained_path_rejects_traversal(tmp_path: Path) -> None:
    from psynet.audit.artifacts import contained_path

    root = tmp_path / "static"
    root.mkdir()
    (root / "ok.js").write_text("ok\n", encoding="utf-8")
    assert contained_path(root, "ok.js") == (root / "ok.js").resolve()
    assert contained_path(root, "../ok.js") is None
    assert contained_path(root, "/etc/passwd") is None


def test_copy_monitor_static_assets_skips_traversal(tmp_path: Path) -> None:
    from psynet.audit.artifacts import copy_monitor_static_assets

    html_dir = tmp_path / "blob"
    html_dir.mkdir()
    # Traversal refs must not create files outside html_dir/static
    copy_monitor_static_assets(
        html_dir, ["../outside.js", "scripts/network-monitor.js"]
    )
    assert not (tmp_path / "outside.js").exists()
    assert (html_dir / "static/scripts/network-monitor.js").is_file()


def test_sanitize_html_ignores_traversing_static_ref(tmp_path: Path) -> None:
    source = tmp_path / "monitor.html"
    source.write_text(
        "<!doctype html><html><head></head><body>"
        '<script src="/static/../secrets.txt"></script>'
        '<script src="/static/scripts/network-monitor.js"></script>'
        "</body></html>",
        encoding="utf-8",
    )
    sanitize_html_artifact(source)
    assert not (tmp_path / "secrets.txt").exists()
    assert (tmp_path / "static/scripts/network-monitor.js").is_file()
