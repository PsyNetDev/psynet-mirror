// Merge live chat frames that raced the first history snapshot.
//
// History is a bag of sender+content lines, not unique keys. Two identical
// "ok"s in the pending window must survive if the snapshot only contains one.

export function leftoverLiveAfterHistory(messages, pendingLive) {
    var remaining = Object.create(null);
    (messages || []).forEach(function (historyMsg) {
        var key = _chatLineKey(historyMsg);
        remaining[key] = (remaining[key] || 0) + 1;
    });
    return (pendingLive || []).filter(function (liveMsg) {
        var key = _chatLineKey(liveMsg);
        if (remaining[key] > 0) {
            remaining[key] -= 1;
            return false;
        }
        return true;
    });
}

function _chatLineKey(msg) {
    return String(msg.sender) + "\0" + String(msg.content || "");
}
