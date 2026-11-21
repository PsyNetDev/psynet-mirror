export function activate({root}) {
    const word = root.querySelector("#word");
    let response = null;
    let shown = null;

    async function click(event) {
        const button = event.target.closest("#answer-button, #reject-button");
        if (button === null || response === null) return;
        const current = response;
        response = null;
        const answer = button.id === "reject-button" ? "reject" : shown;
        if (!(await current.answer(answer))) response = current;
    }

    root.addEventListener("click", click);
    return {
        update({contents, response: handle}) {
            shown = contents.word;
            word.textContent = contents.word;
            response = handle;
            handle.startClock();
        },
        cleanup: () => root.removeEventListener("click", click),
    };
}
