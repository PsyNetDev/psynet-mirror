// Built-in modular-page chatroom widget.
//
// This script is activated for each hosting page through ChatRoom's
// get_js_page_modules() hook. Per-page state stays inside activate(), and the
// returned cleanup function owns all listeners and the WebSocket it creates.
import { leftoverLiveAfterHistory } from "./chatroom-history-merge.mjs";

export async function activate({root, vars}) {
    var CONFIG       = vars["chatroom_config"] || {};
    var ROOM_ID      = CONFIG.room_id;
    var GLOBAL_CH    = CONFIG.channel;
    var SHOW_PARTS   = CONFIG.show_participants;
    var SHOW_HISTORY = CONFIG.show_history;
    var MY_ID        = String(dallinger.identity.participantId);

    var chatConnection = null;
    var leftChat       = false;
    var sendButton     = null;
    var input          = null;
    // When show_history is set, Send stays off until the first history
    // snapshot arrives (empty still counts). Live frames that race that
    // snapshot are held and appended afterwards by count, not existence.
    var historyReady   = !SHOW_HISTORY;
    var pendingLive    = [];

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

    function enableChat() {
        if (leftChat || !sendButton) return;
        sendButton.disabled = false;
    }

    function applyHistorySnapshot(messages) {
        messages.forEach(renderMessage);
    }

    function finishHistoryLoad(messages) {
        messages = messages || [];
        if (historyReady) {
            // After the first snapshot, history is only catch-up for an
            // empty feed (a persist republish after the partner missed live).
            var feed = root.querySelector("#chatroom-messages");
            if (!messages.length || feed.childElementCount > 0) {
                return;
            }
            applyHistorySnapshot(messages);
            return;
        }
        applyHistorySnapshot(messages);
        leftoverLiveAfterHistory(messages, pendingLive).forEach(renderMessage);
        pendingLive = [];
        historyReady = true;
        enableChat();
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
                    if (SHOW_HISTORY && !historyReady) {
                        chatConnection.send({
                            type: "request_state",
                            room_id: ROOM_ID,
                            sender: MY_ID,
                        });
                        return;
                    }
                    enableChat();
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
                    if (!historyReady) {
                        pendingLive.push(msg);
                        return;
                    }
                    renderMessage(msg);
                } else if (msg.type === "occupancy_update") {
                    if (SHOW_PARTS) rebuildParticipantList(msg.participants || []);
                } else if (msg.type === "history") {
                    if (SHOW_HISTORY && historyIsForMe(msg)) {
                        finishHistoryLoad(msg.messages || []);
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
