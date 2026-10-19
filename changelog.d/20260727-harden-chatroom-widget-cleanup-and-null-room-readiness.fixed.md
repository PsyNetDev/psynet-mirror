Hardened chatroom widget cleanup: WebSocket and DOM listeners are removed if page-module activation fails mid-setup, and the null-room path waits for ``pageReady`` before continuing.
