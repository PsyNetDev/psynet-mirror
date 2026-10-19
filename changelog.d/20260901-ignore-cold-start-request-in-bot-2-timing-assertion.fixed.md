The ``bot_2`` demo timing check no longer treats the first recorded HTTP
request as a failure. That cold-start load can exceed one second on busy CI
runners while later pages remain fast.
