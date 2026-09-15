export async function activate({root, trial, vars}) {
    const score = root.querySelector("#abcScore");
    const content = vars["music_notation_prompt"].content;

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
