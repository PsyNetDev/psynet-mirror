// activate() must return a cleanup function or {update, cleanup}, not a node.
export function activate({root}) {
    return root;
}
