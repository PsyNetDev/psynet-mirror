import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { leftoverLiveAfterHistory } from "../../psynet/static/scripts/chatroom-history-merge.mjs";

describe("leftoverLiveAfterHistory", () => {
    it("keeps two pending lives when the first snapshot is empty", () => {
        const leftover = leftoverLiveAfterHistory(
            [],
            [
                { sender: "1", content: "hello" },
                { sender: "1", content: "there" },
            ]
        );
        assert.deepEqual(
            leftover.map((msg) => msg.content),
            ["hello", "there"]
        );
    });

    it("keeps a second identical pending line when history only has one", () => {
        const leftover = leftoverLiveAfterHistory(
            [{ sender: "1", content: "ok" }],
            [
                { sender: "1", content: "ok" },
                { sender: "1", content: "ok" },
            ]
        );
        assert.deepEqual(
            leftover.map((msg) => msg.content),
            ["ok"]
        );
    });

    it("drops pending lines already counted in the snapshot", () => {
        const leftover = leftoverLiveAfterHistory(
            [
                { sender: "1", content: "ok" },
                { sender: "1", content: "ok" },
            ],
            [
                { sender: "1", content: "ok" },
                { sender: "1", content: "ok" },
            ]
        );
        assert.deepEqual(leftover, []);
    });

    it("appends a live line that is not in the snapshot", () => {
        const leftover = leftoverLiveAfterHistory(
            [{ sender: "1", content: "prior" }],
            [{ sender: "2", content: "new" }]
        );
        assert.deepEqual(leftover, [{ sender: "2", content: "new" }]);
    });
});
