import hashlib
import os
import re
import zipfile
from importlib import resources
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from flask import Flask, Response

from psynet.static_resources import (
    STATIC_ENTRY_POINT_GROUP,
    _discover_static_packages,
    apply_versioned_static_cache_headers,
    cacheable_static_url,
    clear_static_package_cache,
    get_static_packages,
    package_static_url,
    versioned_url_for,
)


class FakeEntryPoint:
    def __init__(self, name, loaded, distribution="test-distribution"):
        self.name = name
        self._loaded = loaded
        self.dist = SimpleNamespace(name=distribution)

    def load(self):
        return self._loaded


def test_package_static_url_is_namespaced_and_escaped():
    assert (
        package_static_url("My_Component.Package", "icons/play button.js")
        == "/static/packages/my-component-package/icons/play%20button.js"
    )


@pytest.mark.parametrize(
    "namespace, path",
    [
        ("", "widget.js"),
        ("invalid namespace", "widget.js"),
        ("package", ""),
        ("package", "../widget.js"),
        ("package", "/widget.js"),
        ("package", r"scripts\widget.js"),
        ("package", "https://example.com/widget.js"),
        ("package", "widget.js?version=1"),
        ("package", "widget.js#fragment"),
        ("package", "%2e%2e/secret.js"),
        ("package", "%00.js"),
    ],
)
def test_package_static_url_rejects_unsafe_values(namespace, path):
    with pytest.raises(ValueError):
        package_static_url(namespace, path)


def test_discovers_callable_static_root(tmp_path):
    root = tmp_path / "static"
    root.mkdir()
    (root / "widget.js").write_text("window.widget = true;", encoding="utf-8")
    entry_point = FakeEntryPoint("My_Component", lambda: root)

    packages = _discover_static_packages([entry_point])

    assert len(packages) == 1
    package = packages[0]
    assert package.namespace == "my-component"
    assert package.root == root
    assert package.distribution == "test-distribution"
    assert package.extra_file == (root, "/static/packages/my-component")


def test_discovers_conventional_module_static_root(tmp_path, monkeypatch):
    package_root = tmp_path / "my_components"
    static_root = package_root / "static"
    static_root.mkdir(parents=True)
    module = ModuleType("my_components")
    monkeypatch.setattr(
        "psynet.static_resources.resources.files",
        lambda loaded: package_root,
    )

    packages = _discover_static_packages([FakeEntryPoint("components", module)])

    assert packages[0].root == static_root


def test_materializes_zip_backed_static_root(tmp_path):
    archive_path = tmp_path / "components.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("static/widget.js", "window.widget = true;")

    with zipfile.ZipFile(archive_path) as archive:
        root = zipfile.Path(archive, "static/")
        package = _discover_static_packages(
            [FakeEntryPoint("zip-components", lambda: root)]
        )[0]

    assert isinstance(package.root, Path)
    assert os.path.isdir(package.root)
    assert package.root.joinpath("widget.js").read_text(encoding="utf-8") == (
        "window.widget = true;"
    )


def test_discovery_is_deterministic(tmp_path):
    root = tmp_path / "static"
    root.mkdir()
    packages = _discover_static_packages(
        [
            FakeEntryPoint("z-package", lambda: root),
            FakeEntryPoint("a-package", lambda: root),
        ]
    )

    assert [package.namespace for package in packages] == [
        "a-package",
        "z-package",
    ]


def test_duplicate_canonical_names_are_rejected(tmp_path):
    root = tmp_path / "static"
    root.mkdir()

    with pytest.raises(
        ValueError,
        match="duplicate.*my-package.*first-distribution.*second-distribution",
    ):
        _discover_static_packages(
            [
                FakeEntryPoint("my_package", lambda: root, "first-distribution"),
                FakeEntryPoint("my.package", lambda: root, "second-distribution"),
            ]
        )


def test_missing_static_root_is_rejected(tmp_path):
    missing = tmp_path / "missing"

    with pytest.raises(ValueError, match="does not exist"):
        _discover_static_packages([FakeEntryPoint("missing-package", lambda: missing)])


def test_file_static_root_is_rejected(tmp_path):
    file_path = tmp_path / "widget.js"
    file_path.write_text("window.widget = true;", encoding="utf-8")

    with pytest.raises(ValueError, match="is not a directory"):
        _discover_static_packages([FakeEntryPoint("file-package", lambda: file_path)])


def test_invalid_entry_point_payload_is_rejected():
    with pytest.raises(ValueError, match="package module or a callable"):
        _discover_static_packages([FakeEntryPoint("invalid-package", object())])


def test_entry_point_group_name_is_stable():
    assert STATIC_ENTRY_POINT_GROUP == "psynet.static"


def test_static_package_cache_can_be_cleared():
    get_static_packages()

    clear_static_package_cache()

    assert get_static_packages.cache_info().currsize == 0


def test_psynet_registers_its_static_resource_root():
    package = next(
        package for package in get_static_packages() if package.namespace == "psynet"
    )

    assert package.root.joinpath("scripts/music-notation-prompt.js").is_file()
    assert package.extra_file[1] == "/static/packages/psynet"


def test_experiment_stages_registered_static_packages():
    from psynet.experiment import Experiment

    package_files = [
        (source, destination)
        for source, destination in Experiment.extra_files()
        if destination == "/static/packages/psynet"
    ]

    assert len(package_files) == 1
    source, destination = package_files[0]
    assert os.path.isdir(os.fspath(source))
    assert source.joinpath("scripts/music-notation-prompt.js").is_file()
    assert destination == "/static/packages/psynet"


def test_psynet_layout_script_is_staged():
    from psynet.experiment import Experiment

    staged = [
        (source, destination)
        for source, destination in Experiment.extra_files()
        if destination == "/static/scripts/psynet.layout.js"
    ]

    assert len(staged) == 1
    source, destination = staged[0]
    assert Path(os.fspath(source)).is_file()
    assert Path(os.fspath(source)).name == "psynet.layout.js"


def test_static_url_version_tracks_file_contents(tmp_path):
    static_root = tmp_path / "static"
    static_root.mkdir()
    stylesheet = static_root / "theme.css"
    stylesheet.write_text("body { color: red; }", encoding="utf-8")
    app = Flask("static-cache-test", static_folder=static_root)

    with app.test_request_context("/"):
        first = cacheable_static_url("static/theme.css")
        same = cacheable_static_url("/static/theme.css")
        stylesheet.write_text("body { color: blue; }", encoding="utf-8")
        changed = cacheable_static_url("static/theme.css")

    assert first == same
    assert first.startswith("/static/theme.css?v=")
    assert changed.startswith("/static/theme.css?v=")
    assert changed != first


def test_versioned_url_for_only_versions_local_static_files(tmp_path):
    static_root = tmp_path / "static"
    static_root.mkdir()
    (static_root / "app.js").write_text("window.ready = true;", encoding="utf-8")
    app = Flask("static-url-test", static_folder=static_root)
    app.add_url_rule("/", endpoint="index", view_func=lambda: "")

    with app.test_request_context("/"):
        assert versioned_url_for("static", filename="app.js").startswith(
            "/static/app.js?v="
        )
        assert versioned_url_for("index") == "/"


def test_static_url_versioning_is_disabled_without_a_static_route():
    app = Flask("no-static-route", static_folder=None)

    with app.test_request_context("/"):
        assert cacheable_static_url("/static/app.js") == "/static/app.js"


def test_versioned_static_response_is_public_and_immutable(tmp_path):
    static_root = tmp_path / "static"
    static_root.mkdir()
    (static_root / "app.js").write_text("window.ready = true;", encoding="utf-8")
    app = Flask("static-header-test", static_folder=static_root)

    with app.test_request_context("/static/app.js"):
        unversioned = apply_versioned_static_cache_headers(Response())
    with app.test_request_context(_versioned_url_for_for_test(app, "app.js")):
        versioned = apply_versioned_static_cache_headers(Response())
    with app.test_request_context("/static/app.js?v=stale"):
        stale = apply_versioned_static_cache_headers(Response())

    assert unversioned.cache_control.max_age is None
    assert not unversioned.cache_control.immutable
    assert versioned.cache_control.public
    assert versioned.cache_control.max_age == 31_536_000
    assert versioned.cache_control.immutable
    assert stale.cache_control.max_age is None
    assert not stale.cache_control.immutable


def test_experiment_after_request_versions_literal_percent_filename(tmp_path):
    from psynet.experiment import Experiment

    static_root = tmp_path / "static"
    static_root.mkdir()
    (static_root / "%20.js").write_text("window.ready = true;", encoding="utf-8")
    app = Flask("static-percent-path", static_folder=static_root)
    versioned_url = _versioned_url_for_for_test(app, "%20.js")

    with app.test_request_context(versioned_url) as request_context:
        Experiment.before_request()
        response = Experiment.after_request(request_context.request, Response())

    assert response.cache_control.immutable


@pytest.mark.parametrize(
    "path",
    ["/timeline/arrival_notice", "/timeline/progress_and_reward"],
)
def test_experiment_after_request_does_not_store_live_timeline_json(path):
    """Partner-ready and progress JSON must re-hit the server, not a cached GET."""
    from psynet.experiment import Experiment

    app = Flask("timeline-json-cache")
    with app.test_request_context(path) as request_context:
        Experiment.before_request()
        response = Experiment.after_request(request_context.request, Response())

    assert response.headers.get("Cache-Control") == "no-store"


def test_participant_font_references_use_their_content_versions():
    css_root = resources.files("psynet") / "resources/css"
    css = css_root.joinpath("participant.css").read_text(encoding="utf-8")
    references = re.findall(
        r'url\("fonts/font-files/([^"?]+)\?v=([0-9a-f]+)"\)',
        css,
    )

    assert references
    for filename, version in references:
        contents = css_root.joinpath("fonts/font-files", filename).read_bytes()
        assert version == hashlib.sha256(contents).hexdigest()[:12]


def test_theme_preloads_and_fallback_cover_rendered_font_weights():
    templates = resources.files("psynet") / "templates"
    css = (resources.files("psynet") / "resources/css/participant.css").read_text(
        encoding="utf-8"
    )
    theme = templates.joinpath("theme.html").read_text(encoding="utf-8")

    preloaded = set(re.findall(r"filename='css/fonts/font-files/([^']+)'", theme))
    referenced = set(re.findall(r"fonts/font-files/([^?]+)\?v=", css))
    fallback_weights = {
        int(weight)
        for weight in re.findall(
            r'font-family: "Inter Fallback";.*?font-weight: (\d+);',
            css,
            flags=re.DOTALL,
        )
    }

    assert preloaded == {
        "Inter-Regular.woff2",
        "Inter-Medium.woff2",
        "Inter-Bold.woff2",
    }
    assert preloaded <= referenced
    assert fallback_weights == {400, 500, 700}


def _versioned_url_for_for_test(app, filename):
    """Build a versioned URL while its application context is active."""
    with app.test_request_context("/"):
        return versioned_url_for("static", filename=filename)
