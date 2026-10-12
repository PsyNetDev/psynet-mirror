Fixed an intermittent failure in the timeline hold client Playwright test. Its busy livelock check no longer waits for timers to fire, so wakes left over from earlier steps cannot affect the result.
