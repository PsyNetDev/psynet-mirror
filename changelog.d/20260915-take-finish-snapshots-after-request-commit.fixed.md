Fixed participant-finish local snapshots so they run after the finishing
transaction commits, both on HTTP ``/response`` and outside a request.
The previous in-request snapshot could omit the final response while still
suppressing the shutdown snapshot.
