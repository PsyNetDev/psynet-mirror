Fixed participant-finish local snapshots so they run after the finishing
request commits. The previous in-request snapshot could omit the final
response while still suppressing the shutdown snapshot.
