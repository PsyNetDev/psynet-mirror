import json

from psynet.audit.model import AuditFile, classify_audit_evidence


def file(path: str, content: str | None = "") -> AuditFile:
    return AuditFile(
        path=path,
        url=f"static/{path}",
        content=content,
        size_bytes=len(content or ""),
        kind=path.rsplit(".", 1)[-1] if "." in path else "file",
    )


def test_classify_audit_evidence_matches_dashboard_conventions() -> None:
    view = classify_audit_evidence(
        [
            file("participant.mp4", None),
            file("screenshots/01-intro.png", None),
            file(
                "screenshots/manifest.json",
                json.dumps(
                    {
                        "captions": {
                            "screenshots/01-intro.png": "Intro screen",
                        },
                    }
                ),
            ),
            file("performance.json", json.dumps({"results": [{"n_bots": 4}]})),
            file("monitor.html", "<html></html>"),
            file("data.zip", None),
            file("simulated_data.zip", None),
            file("analyses/analysis.ipynb", json.dumps({"cells": []})),
            file("logs/debug.log", "debug"),
        ]
    )

    assert view.participant_video is not None
    assert [screenshot.path for screenshot in view.screenshots] == [
        "screenshots/01-intro.png",
    ]
    assert view.screenshot_captions == {"screenshots/01-intro.png": "Intro screen"}
    assert view.performance_results == [{"n_bots": 4}]
    assert view.monitor_file is not None
    assert view.data_file is not None
    assert view.simulated_data_file is not None
    assert view.has_analysis_notebook
    assert [file.path for file in view.visible_files] == [
        "logs/debug.log",
    ]


def test_classify_audit_evidence_accepts_standalone_artifact_paths() -> None:
    view = classify_audit_evidence(
        [
            file("artifacts/participant.mp4", None),
            file("artifacts/screenshots/01-intro.png", None),
            file(
                "artifacts/screenshots/manifest.json",
                json.dumps(
                    {
                        "captions": {
                            "screenshots/01-intro.png": "Intro screen",
                        },
                    }
                ),
            ),
            file(
                "artifacts/performance.json", json.dumps({"results": [{"n_bots": 4}]})
            ),
            file("artifacts/monitor.html", "<html></html>"),
            file("artifacts/data.zip", None),
            file("artifacts/simulated_data.zip", None),
            file("analyses/analysis.ipynb", json.dumps({"cells": []})),
        ]
    )

    assert view.participant_video is not None
    assert view.screenshots[0].path == "artifacts/screenshots/01-intro.png"
    assert view.screenshot_captions["screenshots/01-intro.png"] == "Intro screen"
    assert view.performance_file is not None
    assert view.monitor_file is not None
    assert view.data_file is not None
    assert view.simulated_data_file is not None
    assert view.analysis_notebook_file is not None
    assert {item.key: item.present for item in view.completeness} == {
        "participant_video": True,
        "screenshots": True,
        "performance": True,
        "monitor": True,
        "data": True,
        "simulated_data": True,
        "analyses": True,
    }
