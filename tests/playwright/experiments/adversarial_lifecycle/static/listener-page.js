export async function activate({psynet, vars}) {
    const pageName = vars["adversarial_listener"].page_name;
    window.__adversarialLifecycle = window.__adversarialLifecycle || {
        listenerClicks: 0,
        cleanupCalls: 0,
        activations: [],
    };
    window.__adversarialLifecycle.activations.push(pageName);

    psynet.addPageEventListener(window, "click", function () {
        window.__adversarialLifecycle.listenerClicks += 1;
    });

    psynet.addPageCleanupCallback(function () {
        window.__adversarialLifecycle.cleanupCalls += 1;
    });
}
