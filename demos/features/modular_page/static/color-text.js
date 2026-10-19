export async function activate({root, psynet}) {
    const input = root.querySelector("#text-input");

    function stageResponse() {
        psynet.response.staged.rawAnswer = input.value;
    }

    psynet.setStageResponseHandler(stageResponse);
}
