export async function activate({root, vars, psynet}) {
    let roomId = vars.chatroom_room_id;
    const globalChannel = vars.chatroom_global_channel;
    const label = vars.chatroom_room_label;
    const showHistory = vars.chatroom_show_history;
    const participantId = String(dallinger.identity.participantId);
    let chatSocket = null;
    let leftChat = false;
    let pageActive = true;
    let pageLoadedTimer = null;

    // roomId can be absent after browser-history navigation. Wait until the
    // timeline is initialized before advancing, as the legacy script did.
    if (roomId === null || roomId === undefined) {
        function waitForPage() {
            if (!pageActive) return;
            if (!psynet.pageReady) {
                pageLoadedTimer = window.setTimeout(waitForPage, 50);
                return;
            }
            psynet.nextPage();
        }
        waitForPage();

        return function cleanup() {
            pageActive = false;
            window.clearTimeout(pageLoadedTimer);
        };
    }

    roomId = String(roomId);
    const historyAbortController = new AbortController();
    root.querySelector("#chatroom-room-label").textContent = label;

    function leaveChat({advance = true} = {}) {
        if (leftChat) return;
        leftChat = true;
        try {
            if (chatSocket) {
                chatSocket.send(globalChannel + ":" + JSON.stringify({
                    type: "leave_room",
                    room_id: roomId,
                    sender: participantId,
                }));
            }
        } catch (error) {
            psynet.log.warn("Could not send the chatroom leave message.", error);
        }
        if (advance) {
            psynet.nextPage();
        }
    }

    function renderMessage(message) {
        const feed = root.querySelector("#chatroom-messages");
        const paragraph = document.createElement("p");
        const sender = document.createElement("strong");
        sender.textContent = "Participant " + message.sender + ": ";
        paragraph.appendChild(sender);
        paragraph.appendChild(document.createTextNode(message.content || ""));
        feed.appendChild(paragraph);
        feed.scrollTop = feed.scrollHeight;
    }

    function rebuildParticipantList(participants) {
        const list = root.querySelector("#chatroom-participants");
        list.innerHTML = "";
        participants.forEach(function (id) {
            const item = document.createElement("li");
            item.id = "participant-" + id;
            item.textContent = "Participant " + id;
            list.appendChild(item);
        });
        const count = participants.length;
        root.querySelector("#participant-count").textContent = count;
        root.querySelector("#participant-count-plural").textContent =
            count === 1 ? "" : "s";
    }

    async function fetchHistory() {
        const query = new URLSearchParams({
            room_id: roomId,
            participant_id: participantId,
            unique_id: psynet.uniqueId,
        });
        try {
            const response = await fetch("/chatroom_history?" + query, {
                signal: historyAbortController.signal,
            });
            const data = await response.json();
            if (!pageActive || !data.messages || data.messages.length === 0) return;
            const feed = root.querySelector("#chatroom-messages");
            feed.innerHTML = "";
            data.messages.forEach(renderMessage);
        } catch (error) {
            if (pageActive && error.name !== "AbortError") {
                psynet.log.warn("Could not load chatroom history.", error);
            }
        }
    }

    const wsScheme = location.protocol === "https:" ? "wss://" : "ws://";
    chatSocket = new ReconnectingWebSocket(
        wsScheme + location.host + "/chat?channel=" + globalChannel
        + "&worker_id=" + dallinger.identity.workerId
        + "&participant_id=" + participantId
    );

    let firstOpen = true;
    chatSocket.onopen = function () {
        if (leftChat) return;
        chatSocket.send(globalChannel + ":" + JSON.stringify({
            type: "join_room",
            room_id: roomId,
            sender: participantId,
        }));
        chatSocket.send(globalChannel + ":" + JSON.stringify({
            type: "request_occupancy",
        }));
        if (firstOpen && showHistory) {
            fetchHistory();
        }
        firstOpen = false;
    };

    chatSocket.onmessage = function (event) {
        if (event.data.indexOf(globalChannel + ":") !== 0) return;
        let message;
        try {
            message = JSON.parse(event.data.slice(globalChannel.length + 1));
        } catch (error) {
            return;
        }
        if (message.type === "occupancy_update") {
            const roomData = message.rooms && message.rooms[roomId];
            rebuildParticipantList(roomData ? roomData.participants || [] : []);
            return;
        }
        if (String(message.room_id) === roomId && message.type === "message") {
            renderMessage(message);
        }
    };

    const sendButton = root.querySelector("#send-btn");
    const leaveButton = root.querySelector("#leave-btn");
    const input = root.querySelector("#chat-input");

    function sendMessage() {
        const text = input.value.trim();
        if (!text) return;
        chatSocket.send(globalChannel + ":" + JSON.stringify({
            type: "message",
            room_id: roomId,
            content: text,
            sender: participantId,
        }));
        input.value = "";
        input.focus();
    }

    function handleLeave() {
        leaveChat();
    }

    function handleKeypress(event) {
        if (event.key === "Enter") {
            sendButton.click();
            event.preventDefault();
        }
    }

    sendButton.addEventListener("click", sendMessage);
    leaveButton.addEventListener("click", handleLeave);
    input.addEventListener("keypress", handleKeypress);

    return function cleanup() {
        pageActive = false;
        leaveChat({advance: false});
        historyAbortController.abort();
        chatSocket.onopen = null;
        chatSocket.onmessage = null;
        chatSocket.close();
    };
}
