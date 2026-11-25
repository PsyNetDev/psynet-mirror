export function activate({config}) {
    globalThis.eval(config["execute_front_end_js"]);
}
