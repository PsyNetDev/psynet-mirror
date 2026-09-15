export async function activate({psynet, vars}) {
    const config = vars["same_session_unity"];
    psynet.page.attributes = config.attributes;
    psynet.page.contents = config.contents;
    window.__sameSessionUnityMessages = window.__sameSessionUnityMessages || [];
    window.unityInstance = {
        SendMessage: function (objectName, methodName, payload) {
            window.__sameSessionUnityMessages.push({
                objectName: objectName,
                methodName: methodName,
                payload: JSON.parse(payload),
            });
        },
    };
}
