import importlib.util
import subprocess
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "already_tested", ROOT / "ci" / "already_tested.py"
)
already_tested = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(already_tested)


class _FakeApi:
    def __init__(self, pipelines, trees, jobs):
        self.pipelines = pipelines
        self.trees = trees
        self.jobs = jobs

    def get_first_page(self, path, **params):
        assert path == "merge_requests/7/pipelines"
        return self.pipelines

    def get_all(self, path, **params):
        return self.jobs[path]

    def root_tree(self, sha):
        if sha == "gone":
            raise urllib.error.HTTPError(sha, 404, "Not Found", {}, None)
        return self.trees[sha]


def _pipeline(
    id,
    sha,
    status="success",
    ref="refs/merge-requests/7/merge",
    source="merge_request_event",
    project_id=1,
):
    return {
        "id": id,
        "sha": sha,
        "status": status,
        "ref": ref,
        "source": source,
        "project_id": project_id,
        "web_url": f"p/{id}",
    }


def test_passed_jobs_requires_every_shard_to_succeed():
    jobs = [
        {"name": "tests_python_3_14 1/12", "status": "success"},
        {"name": "tests_python_3_14 2/12", "status": "failed"},
        {"name": "playwright_e2e_default 1/3", "status": "success"},
        {"name": "compatibility_tests: [3.11, 1, 3]", "status": "success"},
        {"name": "docs", "status": "success"},
        {"name": "benchmark_load_sweep", "status": "manual"},
    ]
    assert already_tested.passed_jobs(jobs) == [
        "compatibility_tests",
        "docs",
        "playwright_e2e_default",
    ]


@pytest.mark.parametrize(
    ("pipelines", "expected"),
    [
        # The newest merged-results pipeline with identical files, after
        # skipping one whose commit can no longer be read.
        (
            [
                _pipeline(4, "gone"),
                _pipeline(3, "other"),
                _pipeline(2, "same"),
                _pipeline(1, "same"),
            ],
            (2, ["docs"]),
        ),
        # A newer failure on the same files hides an older pass.
        (
            [_pipeline(5, "same", status="failed"), _pipeline(2, "same")],
            (5, ["pre_commit"]),
        ),
        # Unfinished pipelines, train pipelines, branch pipelines and
        # pipelines in another project (a fork) don't count.
        (
            [
                _pipeline(6, "same", status="running"),
                _pipeline(9, "same", ref="refs/merge-requests/7/train"),
                _pipeline(3, "same", source="push"),
                _pipeline(2, "same", project_id=2),
            ],
            None,
        ),
    ],
)
def test_find_already_passed_uses_newest_pipeline_with_identical_files(
    pipelines, expected
):
    api = _FakeApi(
        pipelines,
        trees={"train": {"a"}, "same": {"a"}, "other": {"b"}},
        jobs={
            "pipelines/2/jobs": [{"name": "docs", "status": "success"}],
            "pipelines/5/jobs": [
                {"name": "docs", "status": "failed"},
                {"name": "pre_commit", "status": "success"},
            ],
        },
    )
    match = already_tested.find_already_passed(
        api, project_id=1, mr_iid="7", sha="train"
    )
    if expected is None:
        assert match is None
    else:
        assert (match[0]["id"], match[1]) == expected


def test_main_runs_everything_when_the_check_fails(tmp_path, monkeypatch):
    output = tmp_path / "already_tested.env"
    monkeypatch.setenv("ALREADY_TESTED_DOTENV", str(output))
    monkeypatch.delenv("CI_API_V4_URL", raising=False)

    assert already_tested.main() == 0
    assert output.read_text() == (
        "ALREADY_PASSED_JOBS=,,\nALREADY_TESTED_PIPELINE_URL=\n"
    )


@pytest.mark.parametrize(
    ("job_name", "event_type", "skipped"),
    [
        ("tests_python_3_14 10/12", "merge_train", True),
        ("compatibility_tests: [3.11, 1, 3]", "merge_train", True),
        ("docs", "merge_train", True),
        ("docs_linkcheck_strict", "merge_train", False),
        ("playwright_e2e_legacy 1/3", "merge_train", False),
        # Outside merge trains the list is ignored, wherever it came from.
        ("docs", "merged_result", False),
    ],
)
def test_skip_hook_ends_only_jobs_that_already_passed(job_name, event_type, skipped):
    result = subprocess.run(
        ["sh", "-c", ". ci/skip-if-already-passed.sh; echo ran-setup"],
        cwd=ROOT,
        env={
            "PATH": "/usr/bin:/bin",
            "CI_JOB_NAME": job_name,
            "CI_MERGE_REQUEST_EVENT_TYPE": event_type,
            "ALREADY_PASSED_JOBS": ",tests_python_3_14,compatibility_tests,docs,",
            "ALREADY_TESTED_PIPELINE_URL": "https://example.com/p/1",
        },
        capture_output=True,
        text=True,
        check=True,
    )
    assert ("ran-setup" not in result.stdout) == skipped
