export function activate({vars}) {
    globalThis.eval(vars["execute_front_end_js"]);
}
