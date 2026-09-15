export async function activate({root, trial}) {
    window.__psynetDeferredPageScript = window.__psynetDeferredPageScript || {
        scriptExecutions: 0,
        trialConstructRuns: 0,
    };

    window.__psynetDeferredPageScript.scriptExecutions += 1;

    trial.onEvent("trialConstruct", function () {
        window.__psynetDeferredPageScript.trialConstructRuns += 1;
        const marker = root.querySelector("#deferred-trial-construct-marker");
        if (marker) {
            marker.dataset.trialConstructHandlerRan = "true";
            marker.textContent = "trialConstruct handler ran";
        }
    });
}
