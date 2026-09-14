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

    var chatConnection = null;
    var leftChat       = false;
    var firstOpen      = true;
    var sendButton     = null;
    var input          = null;

    function leaveChat() {
        if (leftChat) return;
        leftChat = true;
        if (sendButton) sendButton.disabled = true;
        if (!chatConnection) return;
        if (chatConnection.isOpen()) {
            try {
                chatConnection.send({
                    type: "leave_room",
                    room_id: ROOM_ID,
                    sender: MY_ID,
                });
            } catch (error) {
                console.warn("Could not notify the chatroom before leaving.", error);
            }
        }
        try {
            chatConnection.close();
        } catch (error) {
            console.warn("Could not close the chatroom connection cleanly.", error);
        }
    }

    function handleBeforeUnload() {
        leaveChat();
    }

    function sendMessage() {
        var text  = input.value.trim();
        if (!text) return;
        try {
            chatConnection.send({
                type: "message",
                room_id: ROOM_ID,
                content: text,
                sender: MY_ID,
            });
        } catch (error) {
            sendButton.disabled = true;
            console.warn("Chat message was not sent; the draft was retained.", error);
            return;
        }
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

    function historyIsForMe(msg) {
        if (msg.target_participant_id == null || msg.target_participant_id === "") {
            return true;
        }
        return String(msg.target_participant_id) === MY_ID;
    }

    function applyHistorySnapshot(messages) {
        var feed = root.querySelector("#chatroom-messages");
        // Live relays can arrive before catch-up. Filling an already-drawn
        // feed would duplicate those lines; clearing it would drop them when
        // the snapshot is still empty.
        if (!messages.length || feed.childElementCount > 0) {
            return;
        }
        messages.forEach(renderMessage);
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
        sendButton = root.querySelector("#chatroom-send-btn");
        input = root.querySelector("#chatroom-chat-input");
        if (!sendButton || !input) {
            throw new Error(
                "Chatroom widget requires #chatroom-send-btn and #chatroom-chat-input."
            );
        }
        sendButton.disabled = true;

        chatConnection = PsyNetWebSocketChannel.connect({
            channel: GLOBAL_CH,
            onOpen: function () {
                if (leftChat) return;
                try {
                    chatConnection.send({
                        type: "join_room",
                        room_id: ROOM_ID,
                        sender: MY_ID,
                    });
                    if (firstOpen) {
                        if (SHOW_HISTORY) {
                            chatConnection.send({
                                type: "request_state",
                                room_id: ROOM_ID,
                                sender: MY_ID,
                            });
                        }
                        firstOpen = false;
                    }
                    sendButton.disabled = false;
                } catch (error) {
                    sendButton.disabled = true;
                    console.warn("Chatroom connection closed while joining.", error);
                }
            },
            onClose: function () {
                if (!leftChat) sendButton.disabled = true;
            },
            onMessage: function (msg) {
                if (leftChat) return;
                if (String(msg.room_id) !== String(ROOM_ID)) return;

                if (msg.type === "message") {
                    renderMessage(msg);
                } else if (msg.type === "occupancy_update") {
                    if (SHOW_PARTS) rebuildParticipantList(msg.participants || []);
                } else if (msg.type === "history") {
                    if (SHOW_HISTORY && historyIsForMe(msg)) {
                        applyHistorySnapshot(msg.messages || []);
                    }
                }
            },
        });

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
