# README

Minimal real-time chat with PsyNet's high-level `EnableChatrooms` / `ChatRoom`
components. Participants are paired with `SimpleGrouper`, wait for a partner,
then discuss an assigned topic in a shared, persisted room with history — same
core idea as the lower-level websocket chatroom feature demo, with far less
custom code. Above the chat, a `GroupPrompt` shows the pair by pseudonym (in
place of the chat's participant list), and a tick appears when a partner
presses Next; partners then wait for each other at a `GroupBarrier` before
moving on.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).
