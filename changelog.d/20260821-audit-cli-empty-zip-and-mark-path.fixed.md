``psynet simulate --audit`` now fails before running tests when the packet is
missing, rejects empty simulation zips, and marks ``simulation_export`` against
the written zip path. ``psynet performance-test local --audit`` skips
mark-present when no bots succeeded.
