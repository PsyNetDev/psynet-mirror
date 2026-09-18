export async function activate({psynet, trial}) {
    window.__trackedTimerLifecycle = {
        started: false,
        timeoutFired: false,
        intervalTicks: 0,
    };

    window.__scheduleTrackedLifecycleTimers = function () {
        window.__trackedTimerLifecycle.started = true;
        trial.setTimer(function () {
            window.__trackedTimerLifecycle.timeoutFired = true;
            psynet.nextPage("stale-timeout");
        }, 1000);

        trial.setRepeatingTimer(function () {
            window.__trackedTimerLifecycle.intervalTicks += 1;
        }, 25);
    };

    return function cleanup() {
        delete window.__scheduleTrackedLifecycleTimers;
    };
}
