`WorkerAsyncProcess.cancel()` now cancels the queued background job instead of raising an error, because the job is enqueued under an id derived from the process id.
