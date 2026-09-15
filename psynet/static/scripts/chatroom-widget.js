// Built-in modular-page chatroom widget.
//
// This script is activated for each hosting page through ChatRoom's
// get_js_page_modules() hook. Per-page state stays inside activate(), and the
// returned cleanup function owns all listeners and the WebSocket it creates.
export async function activate({root, vars}) {
    var CONFIG       = vars["chatroom_config"] || {};
    var ROOM_ID      = CONFIG.room_id;
    var GLOBAL_CH    = CONFIG.channel;
    var SHOW_PARTS   = CONFIG.show_participants;
    var SHOW_HISTORY = CONFIG.show_history;
    var MY_ID        = String(dallinger.identity.participantId);

    var chatSocket = null;
    var leftChat   = false;
    var firstOpen  = true;
    var sendButton = null;
    var input = null;

    function leaveChat() {
        if (leftChat) return;
        leftChat = true;
        if (!chatSocket) return;
        try {
            chatSocket.send(GLOBAL_CH + ":" + JSON.stringify({
                type: "leave_room",
                room_id: ROOM_ID,
                sender: MY_ID,
            }));
        } catch (e) {}
        try {
            if (typeof chatSocket.close === "function") {
                chatSocket.close();
            }
        } catch (e) {}
    }

    function handleBeforeUnload() {
        leaveChat();
    }

    function sendMessage() {
        var text  = input.value.trim();
        if (!text) return;
        chatSocket.send(GLOBAL_CH + ":" + JSON.stringify({
            type: "message",
            room_id: ROOM_ID,
            content: text,
            sender: MY_ID,
        }));
        input.value = "";
        input.focus();
    }

    function handleKeypress(e) {
        if (e.key === "Enter") {
            sendButton.click();
            e.preventDefault();
        }
    }

    function cleanup() {
        window.removeEventListener("beforeunload", handleBeforeUnload);
        if (sendButton) {
            sendButton.removeEventListener("click", sendMessage);
        }
        if (input) {
            input.removeEventListener("keypress", handleKeypress);
        }
        leaveChat();
    }

    function senderLabel(senderId) {
        return String(senderId) === MY_ID ? "You" : "Participant " + senderId;
    }

    function renderMessage(msg) {
        var feed    = root.querySelector("#chatroom-messages");
        var p       = document.createElement("p");
        var label   = document.createElement("strong");
        label.textContent = senderLabel(msg.sender) + ": ";
        var content = document.createTextNode(msg.content || "");
        p.appendChild(label);
        p.appendChild(content);
        feed.appendChild(p);
        feed.scrollTop = feed.scrollHeight;
    }

    function rebuildParticipantList(ids) {
        var list = root.querySelector("#chatroom-participants");
        list.innerHTML = "";
        ids.forEach(function (id) {
            var li = document.createElement("li");
            li.textContent = String(id) === MY_ID ? "You" : "Participant " + id;
            list.appendChild(li);
        });
    }

    try {
        var wsScheme = location.protocol === "https:" ? "wss://" : "ws://";
        chatSocket = new ReconnectingWebSocket(
            wsScheme + location.host + "/chat?channel=" + GLOBAL_CH
            + "&worker_id=" + dallinger.identity.workerId
            + "&participant_id=" + MY_ID
        );

        chatSocket.onopen = function () {
            if (leftChat) return;
            chatSocket.send(GLOBAL_CH + ":" + JSON.stringify({
                type: "join_room",
                room_id: ROOM_ID,
                sender: MY_ID,
            }));
            if (firstOpen) {
                if (SHOW_HISTORY) {
                    chatSocket.send(GLOBAL_CH + ":" + JSON.stringify({
                        type: "request_state",
                        room_id: ROOM_ID,
                        sender: MY_ID,
                    }));
                }
                firstOpen = false;
            }
        };

        chatSocket.onmessage = function (event) {
            if (leftChat) return;
            if (event.data.indexOf(GLOBAL_CH + ":") !== 0) return;
            var msg;
            try {
                msg = JSON.parse(event.data.slice(GLOBAL_CH.length + 1));
            } catch (e) { return; }

            if (String(msg.room_id) !== String(ROOM_ID)) return;

            if (msg.type === "message") {
                renderMessage(msg);
            } else if (msg.type === "occupancy_update") {
                if (SHOW_PARTS) rebuildParticipantList(msg.participants || []);
            } else if (msg.type === "history") {
                if (SHOW_HISTORY && String(msg.target_participant_id) === MY_ID) {
                    // Clear before re-rendering to avoid duplicates on reconnect.
                    root.querySelector("#chatroom-messages").innerHTML = "";
                    (msg.messages || []).forEach(renderMessage);
                }
            }
        };

        sendButton = root.querySelector("#chatroom-send-btn");
        input = root.querySelector("#chatroom-chat-input");
        if (!sendButton || !input) {
            throw new Error(
                "Chatroom widget requires #chatroom-send-btn and #chatroom-chat-input."
            );
        }

        window.addEventListener("beforeunload", handleBeforeUnload);
        sendButton.addEventListener("click", sendMessage);
        input.addEventListener("keypress", handleKeypress);

        return async function () {
            cleanup();
        };
    } catch (error) {
        cleanup();
        throw error;
    }
}
