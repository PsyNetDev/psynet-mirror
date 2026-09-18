# README

Real-time multi-user interaction uses WebSockets: subscribe the experiment to a
channel, handle `receive_message`, and push occupancy updates with
`publish_to_subscribers`. This demo implements a low-level multi-room chat
(custom pages and `ChatroomDemoMessage` table) rather than the higher-level
`psynet.chatroom` helpers, so you can see join/leave, history, and disconnect
handling end to end.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).
