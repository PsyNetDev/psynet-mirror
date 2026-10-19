function pad(n) {
    return (n.length < 2) ? "0" + n : n;
}

export async function activate({root, psynet}) {
    const slider = psynet.page.control.slider;

    function updateSliderBackground() {
        psynet.log.debug("Updating slider background");
        var rHex = parseInt(root.querySelector("#red").value, 10).toString(16),
            gHex = parseInt(root.querySelector("#green").value, 10).toString(16),
            bHex = parseInt(root.querySelector("#blue").value, 10).toString(16),
            hex = "#" + pad(rHex) + pad(gHex) + pad(bHex);
        root.querySelector("#color-box").style.backgroundColor = hex;
    }

    updateSliderBackground();
    slider.onSliderEvent = updateSliderBackground;
}
