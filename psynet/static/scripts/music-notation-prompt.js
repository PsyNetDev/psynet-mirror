export async function activate({root, trial}) {
    const score = root.querySelector("#abcScore");
    // In the prompt's markup rather than the page's configuration, as it
    // differs from trial to trial.
    const content = score.dataset.abc;

    function renderScore() {
        score.style.visibility = "visible";
        ABCJS.renderAbc(score, content);
    }

    function hideScore() {
        score.style.visibility = "hidden";
    }

    trial.onEvent("promptStart", renderScore);
    trial.onEvent("promptEnd", hideScore);
}
