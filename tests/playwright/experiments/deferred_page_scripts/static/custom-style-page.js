export async function activate({psynet, trial}) {
    trial.onEvent("trialConstruct", function () {
        const button = document.getElementById("next-button");
        psynet.addPageEventListener(button, "click", function () {
            psynet.submitResponse();
        });
    });
}
