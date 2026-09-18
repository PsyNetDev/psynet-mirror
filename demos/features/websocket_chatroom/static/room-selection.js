export async function activate({root, vars, psynet}) {
    const numberOfRooms = vars.num_chatrooms;
    const maxOccupancy = vars.max_occupancy;
    const globalChannel = vars.chatroom_global_channel;
    const buttonContainer = root.querySelector("#room-buttons");

    function buildButtons(rooms) {
        buttonContainer.innerHTML = "";
        for (let index = 0; index < numberOfRooms; index++) {
            const room = (rooms && rooms[String(index)]) || {};
            const count = room.count || 0;
            const full = maxOccupancy != null && count >= maxOccupancy;
            const button = document.createElement("button");
            button.className = "btn btn-primary m-2" + (full ? " disabled" : "");
            button.disabled = full;
            button.dataset.roomIndex = String(index);
            const countLabel = maxOccupancy
                ? count + "/" + maxOccupancy
                : String(count);
            button.innerHTML = "Room " + (index + 1)
                + "<br><small>" + countLabel
                + " participant" + (count === 1 ? "" : "s") + "</small>"
                + (full ? "<br><small>(full)</small>" : "");
            buttonContainer.appendChild(button);
        }
    }

    function selectRoom(event) {
        const button = event.target.closest("button[data-room-index]");
        if (button && !button.disabled) {
            psynet.nextPage(button.dataset.roomIndex);
        }
    }
    buttonContainer.addEventListener("click", selectRoom);

    const wsScheme = location.protocol === "https:" ? "wss://" : "ws://";
    const occupancySocket = new ReconnectingWebSocket(
        wsScheme + location.host + "/chat?channel=" + globalChannel
        + "&worker_id=" + dallinger.identity.workerId
        + "&participant_id=" + dallinger.identity.participantId
    );

    occupancySocket.onopen = function () {
        occupancySocket.send(
            globalChannel + ":" + JSON.stringify({type: "request_occupancy"})
        );
    };

    occupancySocket.onmessage = function (event) {
        if (event.data.indexOf(globalChannel + ":") !== 0) return;
        try {
            const message = JSON.parse(
                event.data.slice(globalChannel.length + 1)
            );
            if (message.type === "occupancy_update") {
                buildButtons(message.rooms || {});
            }
        } catch (error) {
            psynet.log.warn("Could not parse a chatroom occupancy update.", error);
        }
    };

    return function cleanup() {
        occupancySocket.onopen = null;
        occupancySocket.onmessage = null;
        occupancySocket.close();
    };
}
