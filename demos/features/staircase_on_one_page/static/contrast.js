export function activate({root, psynet}) {
    const patches = root.querySelector("#patches");
    let answered = false;

    // Called for the first trial, and again whenever the next trial's page
    // arrives with the same session_id.
    function show() {
        const pair = psynet.page.contents;
        for (const side of ["left", "right"]) {
            const grey = pair[side];
            root.querySelector(`#${side}-patch`).style.backgroundColor = `rgb(${grey}, ${grey}, ${grey})`;
        }
        patches.style.visibility = "visible";
        answered = false;
    }

    async function keydown(event) {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        if (answered || event.repeat) return;
        answered = true;
        patches.style.visibility = "hidden";
        if (!(await psynet.nextPage(event.key === "ArrowLeft" ? "left" : "right"))) show();
    }

    psynet.trial.onEvent("pageUpdated", show);
    show();
    document.addEventListener("keydown", keydown);
    return () => document.removeEventListener("keydown", keydown);
}
