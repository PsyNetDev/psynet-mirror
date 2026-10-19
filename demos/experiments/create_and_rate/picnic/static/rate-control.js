export function activate({root, psynet}) {
    function validate() {
        const ruleDict = {};
        let nChecked = 0;
        root.querySelectorAll("input").forEach(function (element) {
            if (element.checked) {
                nChecked += 1;
            }
            ruleDict[element.id] = {
                "checked": element.checked,
                "rule": element.value
            };
        });
        if (nChecked > 0) {
            psynet.nextPage(ruleDict);
        } else {
            alert("You need to interact with the page before you can continue.");
        }
    }

    function handleChange(event) {
        if (event.target.value === "none") {
            root.querySelectorAll(".rules").forEach(function (element) {
                element.checked = false;
            });
        } else {
            root.querySelector("#none").checked = false;
        }
    }

    const submitButton = root.querySelector("#rate-submit");
    root.addEventListener("change", handleChange);
    submitButton.addEventListener("click", validate);
}
