export async function activate({root}) {
    window.__psynetManagedJavascript.events.push("activate:second");
    const marker = root.querySelector("#managed-javascript-marker");
    marker.dataset.secondActive = "true";
    marker.textContent = "Managed JavaScript activated";

    return async function cleanup() {
        window.__psynetManagedJavascript.events.push("cleanup:second");
    };
}
