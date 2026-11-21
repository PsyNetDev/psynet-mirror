export function activate({root}) {
    const patches = root.querySelector("#patches");
    let response = null;

    function keydown(event) {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        if (response === null || event.repeat) return;
        response.answer(event.key === "ArrowLeft" ? "left" : "right");
        response = null;
        patches.style.visibility = "hidden";
    }

    document.addEventListener("keydown", keydown);
    return {
        update({contents, response: handle}) {
            for (const side of ["left", "right"]) {
                const grey = contents[side];
                root.querySelector(`#${side}-patch`).style.backgroundColor = `rgb(${grey}, ${grey}, ${grey})`;
            }
            patches.style.visibility = "visible";
            response = handle;
            handle.startClock();
        },
        cleanup: () => document.removeEventListener("keydown", keydown),
    };
}
