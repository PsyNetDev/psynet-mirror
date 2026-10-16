from pathlib import Path

BOOTSTRAP_DIR = (
    Path(__file__).resolve().parents[2]
    / "psynet"
    / "resources"
    / "libraries"
    / "bootstrap"
)


def test_vendored_bootstrap_is_5_3_8():
    css = (BOOTSTRAP_DIR / "bootstrap.min.css").read_text(encoding="utf-8")
    js = (BOOTSTRAP_DIR / "bootstrap.bundle.min.js").read_text(encoding="utf-8")
    license_text = (BOOTSTRAP_DIR / "LICENSE").read_text(encoding="utf-8")

    assert "Bootstrap  v5.3.8" in css
    assert "Bootstrap v5.3.8" in js
    assert 'static get VERSION(){return"5.3.8"}' in js
    assert "Copyright (c) 2011-2025 The Bootstrap Authors" in license_text
