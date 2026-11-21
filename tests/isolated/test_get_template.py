import json
import re
import subprocess
from importlib import resources

import pytest

from psynet.timeline import get_template, templates


def get_template_legacy(name):
    assert isinstance(name, str)
    return resources.files(templates).joinpath(name).read_text()


def test_get_template():
    page = "timeline-page.html"
    assert get_template(page) == get_template_legacy(page)


def test_start_template_only_creates_on_structured_lookup_errors():
    template = resources.files("psynet").joinpath("templates/start.html").read_text()
    function = re.search(
        r"function shouldAttemptCreate\(resp\) \{.*?^\s*\}",
        template,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert function is not None
    responses = [
        {"status": 403, "errorCode": "participant_not_found"},
        {"status": 403, "errorCode": "assignment_id_missing"},
        {"status": 403, "errorCode": "other_forbidden_error"},
        {"status": 403},
        {"status": 500, "errorCode": "participant_not_found"},
        None,
    ]
    script = (
        f"{function.group(0)}\n"
        f"console.log(JSON.stringify({json.dumps(responses)}"
        ".map(response => shouldAttemptCreate(response))));"
    )

    result = subprocess.run(
        ["node", "-e", script], check=True, capture_output=True, text=True
    )

    assert json.loads(result.stdout) == [True, True, False, False, False, False]
    assert "/participant/" not in template
    assert "pageshow" in template
    assert "event.persisted" in template


START_PAGE_HARNESS = """
const posts = [];
let redirect = null;
const responses = %s;
globalThis.location = {search: "?workerId=W&assignmentId=A&hitId=H"};
globalThis.window = {
    location: {replace: (url) => { redirect = url; }},
    addEventListener: (event, listener) => listener({persisted: false}),
};
globalThis.document = {getElementById: () => ({hidden: true})};
globalThis.Fingerprint2 = function () { this.get = (done) => done("fp"); };
globalThis.dallinger = {post: (route, data) => {
    posts.push([route, data]);
    return {done: (callback) => {
        setTimeout(() => callback(responses[route]));
        return {fail: () => {}};
    }};
}};
process.once("beforeExit", () => console.log(JSON.stringify({posts, redirect})));
%s
"""


@pytest.mark.parametrize(
    "found, routes",
    [
        (None, ["/load-participant", "/participant"]),
        ({"unique_id": "W:A"}, ["/load-participant"]),
    ],
)
def test_start_template_resumes_or_creates_after_a_missing_ok_lookup(found, routes):
    template = resources.files("psynet").joinpath("templates/start.html").read_text()
    script = re.search(r"<script>(.*?)</script>", template, flags=re.DOTALL).group(1)
    responses = {
        "/load-participant": {"participant": found},
        "/participant": {"participant": {"unique_id": "W:A"}},
    }

    result = subprocess.run(
        ["node", "-e", START_PAGE_HARNESS % (json.dumps(responses), script)],
        check=True,
        capture_output=True,
        text=True,
    )

    output = json.loads(result.stdout)
    assert [route for route, _ in output["posts"]] == routes
    assert output["posts"][0][1]["missing_ok"] == "true"
    assert all("missing_ok" not in data for _, data in output["posts"][1:])
    assert output["redirect"] == "/timeline?unique_id=W:A"


def test_start_template_ignores_stale_async_attempts():
    """A bfcache restore must supersede callbacks from the previous flow."""
    template = resources.files("psynet").joinpath("templates/start.html").read_text()

    assert "const attempt = ++startAttempt;" in template
    assert "createParticipant(entryInformation, attempt)" in template
    assert template.count("attempt !== startAttempt") >= 4
    assert template.count('window.location.replace("/timeline?unique_id="') == 2
    assert 'window.location = "/timeline' not in template
