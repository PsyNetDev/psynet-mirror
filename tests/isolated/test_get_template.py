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


START_PAGE_HARNESS = """
const posts = [];
const errors = [];
let redirect = null;
const responses = %s;
globalThis.location = {search: "?workerId=W&assignmentId=A&hitId=H"};
globalThis.window = {
    location: {replace: (url) => { redirect = url; }},
    addEventListener: (event, listener) => {
        if (event === "pageshow") listener({persisted: false});
    },
};
globalThis.document = {getElementById: () => ({hidden: true})};
globalThis.Fingerprint2 = function () { this.get = (done) => done("fp"); };
globalThis.dallinger = {
    error: (resp) => errors.push(resp),
    post: (route, data) => {
        posts.push([route, data]);
        const [ok, body] = responses[route];
        return {done: (onDone) => ({fail: (onFail) => {
            setTimeout(() => (ok ? onDone : onFail)(body));
        }})};
    },
};
process.once("beforeExit", () => console.log(JSON.stringify({posts, errors, redirect})));
%s
"""


@pytest.mark.parametrize(
    "lookup, routes, redirect",
    [
        ([True, {"participant": None}], ["/load-participant", "/participant"], True),
        ([True, {"participant": {"unique_id": "W:A"}}], ["/load-participant"], True),
        ([False, {"status": 500}], ["/load-participant"], False),
    ],
)
def test_start_template_handles_a_missing_ok_lookup(lookup, routes, redirect):
    template = resources.files("psynet").joinpath("templates/start.html").read_text()
    script = re.search(r"<script>(.*?)</script>", template, flags=re.DOTALL).group(1)
    responses = {
        "/load-participant": lookup,
        "/participant": [True, {"participant": {"unique_id": "W:A"}}],
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
    if redirect:
        assert output["redirect"] == "/timeline?unique_id=W:A"
        assert output["errors"] == []
    else:
        assert output["redirect"] is None
        assert output["errors"] == [lookup[1]]


def test_start_template_ignores_stale_async_attempts():
    """A bfcache restore must supersede callbacks from the previous flow."""
    template = resources.files("psynet").joinpath("templates/start.html").read_text()

    assert "const attempt = ++startAttempt;" in template
    assert "createParticipant(entryInformation, attempt)" in template
    assert template.count("attempt !== startAttempt") >= 4
    assert template.count('window.location.replace("/timeline?unique_id="') == 2
    assert 'window.location = "/timeline' not in template
    assert "/participant/" not in template
    assert "pageshow" in template
    assert "event.persisted" in template
