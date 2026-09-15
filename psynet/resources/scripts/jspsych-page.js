export async function activate({root, trial, vars, page, psynet}) {
    const moduleUrl = new URL(
        vars["jspsych_timeline_module"],
        window.location.href
    ).href;
    const timelineModule = await import(moduleUrl);
    if (typeof timelineModule.buildTimeline !== "function") {
        throw new Error(
            `The jsPsych timeline module ${moduleUrl} must export buildTimeline(context).`
        );
    }

    let completed = false;
    let deactivating = false;
    let started = false;
    const jsPsych = initJsPsych({
        display_element: root.querySelector("#js-psych"),
        on_finish: function () {
            completed = true;
            if (!deactivating) {
                return psynet.nextPage(jsPsych.data.get().json());
            }
        }
    });

    function cleanup() {
        deactivating = true;
        if (started && !completed && jsPsych.timeline) {
            jsPsych.endExperiment();
        }
        window.removeEventListener(
            "beforeunload",
            jsPsych.getInitSettings().on_close
        );
        document.documentElement.removeAttribute("jspsych");
        if (globalThis.jsPsych === jsPsych) {
            globalThis.jsPsych = undefined;
        }
    }

    try {
        const timeline = await timelineModule.buildTimeline({
            jsPsych,
            vars,
            page,
            psynet,
            root,
        });
        if (!Array.isArray(timeline)) {
            throw new Error(
                `The jsPsych timeline module ${moduleUrl} must return an array.`
            );
        }
        globalThis.jsPsych = jsPsych;

        trial.onEvent("trialStart", function () {
            trial.setTimer(function () {
                if (deactivating) {
                    return;
                }
                started = true;
                jsPsych.run(timeline).catch(function (error) {
                    if (!deactivating) {
                        psynet.log.error(error.stack || String(error));
                    }
                });
            }, 0);
        });
        return cleanup;
    } catch (error) {
        cleanup();
        throw error;
    }
}
