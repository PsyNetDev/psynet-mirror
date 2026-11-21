export function activate({root, psynet}) {
    const patches = root.querySelector("#patches");
    const pair = psynet.page.contents;
    let answered = false;

    for (const side of ["left", "right"]) {
        const grey = pair[side];
        root.querySelector(`#${side}-patch`).style.backgroundColor = `rgb(${grey}, ${grey}, ${grey})`;
    }
    patches.style.visibility = "visible";

    async function keydown(event) {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        if (answered || event.repeat) return;
        answered = true;
        patches.style.visibility = "hidden";
        if (!(await psynet.nextPage(event.key === "ArrowLeft" ? "left" : "right"))) {
            answered = false;
            patches.style.visibility = "visible";
        }
    }

    document.addEventListener("keydown", keydown);
    return () => document.removeEventListener("keydown", keydown);
}
