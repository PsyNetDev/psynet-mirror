export async function activate({root, page}) {
    window.__psynetManagedJavascript.events.push("activate:first");
    window.__psynetManagedJavascript.pageUuids.push(page.attributes.page_uuid);
    const marker = root.querySelector("#managed-javascript-marker");
    marker.dataset.firstActive = "true";

    return async function cleanup() {
        window.__psynetManagedJavascript.events.push("cleanup:first");
    };
}
