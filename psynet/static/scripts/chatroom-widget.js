// Built-in modular-page chatroom widget.
//
// This script is activated for each hosting page through ChatRoom's
// get_js_page_modules() hook. Per-page state stays inside activate(), and the
// returned cleanup function owns all listeners and the WebSocket it creates.
// The socket is a checked /experiment-socket connection, and the server sends
// room traffic to members only, as directed messages.
import { leftoverLiveAfterHistory } from "./chatroom-history-merge.mjs";

export async function activate({root, vars}) {
    var CONFIG       = vars["chatroom_config"] || {};
    var ROOM_ID      = CONFIG.room_id;
    var CHANNEL      = CONFIG.channel;
    var SHOW_PARTS   = CONFIG.show_participants;
    var SHOW_HISTORY = CONFIG.show_history;
    var YOU_LABEL    = CONFIG.you_label || "You";
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
        chatConnection.send(CHANNEL, {type: "leave_room", room_id: ROOM_ID});
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
        if (chatConnection.raw.readyState !== WebSocket.OPEN) {
            // dallinger.Socket would queue the line; keep it as a draft instead.
            sendButton.disabled = true;
            return;
        }
        chatConnection.send(CHANNEL, {type: "message", room_id: ROOM_ID, content: text});
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

    // The icon HTML comes from the experiment's PseudonymScheme on the
    // server, which escapes the name; message text is only ever set as text.
    function senderLabel(senderId, pseudonym) {
        var label = document.createElement("strong");
        label.className = "chatroom-sender";
        if (pseudonym && pseudonym.icon_html) {
            var icon = document.createElement("span");
            icon.innerHTML = pseudonym.icon_html;
            label.appendChild(icon);
        }
        var name = String(senderId) === MY_ID
            ? YOU_LABEL
            : (pseudonym ? pseudonym.name : "Participant " + senderId);
        label.appendChild(document.createTextNode(name));
        return label;
    }

    function renderMessage(msg) {
        var feed    = root.querySelector("#chatroom-messages");
        var p       = document.createElement("p");
        var label   = senderLabel(msg.sender, msg.sender_pseudonym);
        label.appendChild(document.createTextNode(": "));
        var content = document.createTextNode(msg.content || "");
        p.appendChild(label);
        p.appendChild(content);
        feed.appendChild(p);
        feed.scrollTop = feed.scrollHeight;
    }

    function enableChat() {
        if (leftChat || !sendButton) return;
        sendButton.disabled = false;
    }

    function applyHistorySnapshot(messages) {
        messages.forEach(renderMessage);
    }

    function finishHistoryLoad(messages) {
        if (historyReady) return;
        applyHistorySnapshot(messages);
        leftoverLiveAfterHistory(messages, pendingLive).forEach(renderMessage);
        pendingLive = [];
        historyReady = true;
        enableChat();
    }

    function rebuildParticipantList(ids, pseudonyms) {
        var list = root.querySelector("#chatroom-participants");
        list.innerHTML = "";
        ids.forEach(function (id) {
            var li = document.createElement("li");
            li.appendChild(senderLabel(id, pseudonyms[String(id)]));
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

        chatConnection = dallinger.openExperimentSocket({
            scope: psynetTemplateData.websocketScope,
        });
        chatConnection.onOpen(function () {
            if (leftChat) return;
            // Sent again on every reconnect, since the server may have
            // marked this participant as having left the room.
            chatConnection.send(CHANNEL, {type: "join_room", room_id: ROOM_ID});
            if (SHOW_HISTORY && !historyReady) {
                chatConnection.send(CHANNEL, {type: "request_state", room_id: ROOM_ID});
                return;
            }
            enableChat();
        });
        chatConnection.raw.addEventListener("close", function () {
            if (!leftChat) sendButton.disabled = true;
        });
        chatConnection.onRefused(function (code, reason) {
            sendButton.disabled = true;
            console.warn("The server refused the chatroom connection: " + reason);
        });
        chatConnection.onDirect(function (msg) {
            if (leftChat) return;
            if (!msg || String(msg.room_id) !== String(ROOM_ID)) return;

            if (msg.type === "message") {
                if (!historyReady) {
                    pendingLive.push(msg);
                    return;
                }
                renderMessage(msg);
            } else if (msg.type === "occupancy_update") {
                if (SHOW_PARTS) {
                    rebuildParticipantList(msg.participants || [], msg.pseudonyms || {});
                }
            } else if (msg.type === "history") {
                if (SHOW_HISTORY) finishHistoryLoad(msg.messages || []);
            }
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
