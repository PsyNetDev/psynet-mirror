#!/usr/bin/env python3
"""Find jobs that already passed on identical files, so a merge train can skip them.

A merge-train pipeline tests the commit that ``master`` will become. When
``master`` has not moved since the merge request's last merged-results
pipeline, and nothing is ahead of it in the train, that commit has exactly the
same files as the one the merged-results pipeline tested. Rerunning the suite
then only delays the merge.

This script runs in the ``check_already_tested`` job. It compares the root
tree of the current commit with the commits of the merge request's recent
passing merged-results pipelines. On a match it writes a dotenv file listing
the jobs whose every shard passed there; ``ci/skip-if-already-passed.sh``
then makes those jobs exit early. Any doubt (no match, an API error, a
missing variable) writes an empty list, so every job runs as usual.

It uses only the standard library, because the job runs on a bare Python
image. The project is public, so no token is needed; set
``ALREADY_TESTED_API_TOKEN`` to a ``read_api`` token if anonymous requests
are rate-limited.
"""

import json
import os
import re
import sys
import urllib.parse
import urllib.request

_MAX_CANDIDATES = 3
_SHARD_SUFFIX_RE = re.compile(r"( \d+/\d+|: \[.*\])$")


def base_job_name(name):
    """Strip the ``1/12`` or ``: [3.11, 1, 3]`` suffix GitLab adds to shards."""
    return _SHARD_SUFFIX_RE.sub("", name)


def passed_jobs(jobs):
    """Return the base names of jobs whose every shard succeeded."""
    statuses = {}
    for job in jobs:
        statuses.setdefault(base_job_name(job["name"]), set()).add(job["status"])
    return sorted(name for name, seen in statuses.items() if seen == {"success"})


class _Api:
    def __init__(self, base_url, project_id, token=None):
        self.prefix = f"{base_url}/projects/{project_id}"
        self.headers = {"PRIVATE-TOKEN": token} if token else {}

    def get_all(self, path, **params):
        """GET every page of a list endpoint."""
        items = []
        page = 1
        while True:
            query = urllib.parse.urlencode({**params, "per_page": 100, "page": page})
            request = urllib.request.Request(
                f"{self.prefix}/{path}?{query}", headers=self.headers
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                batch = json.load(response)
                next_page = response.headers.get("X-Next-Page")
            items.extend(batch)
            if not next_page:
                return items
            page = int(next_page)

    def get_first_page(self, path, **params):
        query = urllib.parse.urlencode({**params, "per_page": 20})
        request = urllib.request.Request(
            f"{self.prefix}/{path}?{query}", headers=self.headers
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    def root_tree(self, sha):
        """Return the root tree's entries, which identify the commit's files."""
        return frozenset(
            (entry["name"], entry["id"], entry["mode"])
            for entry in self.get_all("repository/tree", ref=sha)
        )


def find_already_passed(api, *, mr_iid, sha, pipeline_id):
    """Return ``(pipeline, passed job names)`` for a matching pipeline, or ``None``."""
    merged_results_ref = f"refs/merge-requests/{mr_iid}/merge"
    candidates = [
        pipeline
        for pipeline in api.get_first_page(f"merge_requests/{mr_iid}/pipelines")
        if pipeline["status"] == "success"
        and pipeline["ref"] == merged_results_ref
        and pipeline["id"] != pipeline_id
    ][:_MAX_CANDIDATES]
    if not candidates:
        print(f"No passing merged-results pipeline for !{mr_iid}.")
        return None

    current_tree = api.root_tree(sha)
    for pipeline in candidates:
        if api.root_tree(pipeline["sha"]) != current_tree:
            print(f"Pipeline {pipeline['id']} tested different files.")
            continue
        jobs = api.get_all(f"pipelines/{pipeline['id']}/jobs")
        return pipeline, passed_jobs(jobs)
    return None


def main():
    output = os.environ.get("ALREADY_TESTED_DOTENV", "already_tested.env")
    passed = []
    pipeline_url = ""
    try:
        api = _Api(
            os.environ["CI_API_V4_URL"],
            os.environ["CI_PROJECT_ID"],
            os.environ.get("ALREADY_TESTED_API_TOKEN"),
        )
        match = find_already_passed(
            api,
            mr_iid=os.environ["CI_MERGE_REQUEST_IID"],
            sha=os.environ["CI_COMMIT_SHA"],
            pipeline_id=int(os.environ["CI_PIPELINE_ID"]),
        )
        if match:
            pipeline, passed = match
            pipeline_url = pipeline["web_url"]
            print(f"Pipeline {pipeline_url} tested identical files.")
            print("Jobs that passed there and will be skipped: " + ", ".join(passed))
        else:
            print("No pipeline tested identical files; running every job.")
    except Exception as exc:
        print(f"WARNING: could not check for earlier results ({exc!r}); running every job.")
        passed = []
        pipeline_url = ""

    with open(output, "w", encoding="utf-8") as f:
        f.write(f"ALREADY_PASSED_JOBS=,{','.join(passed)},\n")
        f.write(f"ALREADY_TESTED_PIPELINE_URL={pipeline_url}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
