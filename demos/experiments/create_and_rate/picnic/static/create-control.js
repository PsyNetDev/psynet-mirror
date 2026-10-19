export function activate({root, psynet}) {
    function validate() {
        const rule = root.querySelector("#rule").value;
        if (rule === "") {
            alert("Please enter a rule");
            return;
        } else if ((rule.split(" ").length - 1) < 3) {
            alert('Your rule must start with "The rule is:"');
            return;
        }
        const questionsObject = {};
        let success = true;
        ["difficult", "abstract", "helpful_positive", "helpful_negative"].forEach(function (id) {
            const radio = root.querySelector(`input[name="${id}"]:checked`);
            if (radio === null) {
                success = false;
            } else {
                questionsObject[id] = radio.value;
            }
        });
        if (!success) {
            alert("Please answer all questions");
            return;
        }
        psynet.nextPage({
            "rule": rule,
            "questions": questionsObject
        });
    }

    const submitButton = root.querySelector("#create-submit");
    submitButton.addEventListener("click", validate);
}