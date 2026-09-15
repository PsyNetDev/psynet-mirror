export async function activate({root, trial, psynet}) {
    const abortController = new AbortController();

    async function loadApiValues() {
        const requestOptions = {signal: abortController.signal};
        const [digitResponse, nameResponse, pageUuidResponse] = await Promise.all([
            fetch("/api/random_digit_input", requestOptions),
            fetch("/api/hello?name=world", requestOptions),
            fetch("/api/page_uuid", {
                ...requestOptions,
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({participant_id: psynet.participantId}),
            }),
        ]);
        const [digitData, name, pageUuidData] = await Promise.all([
            digitResponse.json(),
            nameResponse.json(),
            pageUuidResponse.json(),
        ]);

        root.querySelector("#digit").textContent = digitData.random_number
            .toString()
            .padStart(7, "0");
        root.querySelector("#name").textContent = name;
        root.querySelector("#page_uuid").textContent = pageUuidData.page_uuid;
    }

    trial.onEvent("trialStart", async function () {
        try {
            await loadApiValues();
        } catch (error) {
            if (error.name !== "AbortError") {
                throw error;
            }
        }
    });

    return function cleanup() {
        abortController.abort();
    };
}
