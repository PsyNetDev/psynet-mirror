# Which way is the bird facing?

Run `psynet debug local` in this directory in a PsyNet source checkout. Press the left or right arrow key to match the direction of the beak in each photograph. The six birds appear once each, in a shuffled order. The final page gives your score from the six saved trials.

## How the pictures get ready

1. In [experiment.py](experiment.py), `preload_fields = ("bird",)` sends the ordered bird IDs to the participant. The correct directions stay on the server.
2. The page declares its six JPEGs in `MediaSpec(image=...)`. Each ID matches a hidden `<img>` on the page, so PsyNet fills that element with a local blob URL when the download completes.
3. At `trialStart`, [birds.js](static/birds.js) awaits `decode()` on all six elements. Like the arrow demo, it uses a typed `TrialAnswer` and explicit prediction. It calls `game.startResponseClock(view)` in the frame that reveals each photograph and `response.answer(value)` on a keypress. Changing birds only toggles visibility.

To see this in browser developer tools, open **Network** on the instruction page, disable the cache, select a slow connection and filter for `/static/birds/`. Press **Next**. Six JPEGs download before the first bird appears. Play through the round with the panel open. The request count stays at six while the pictures change. Reloading the game page preloads its media again and resumes at the first unanswered bird.

The [arrow flanker](../live_trial_game) uses the same live-trial pattern with text stimuli. [VocabTest](../../../psynet/resources/scripts/vocabtest.js) shows how to fetch just the next few images for a longer deck.

## Photographs

These photographs are bundled as 600 × 400 JPEGs. The U.S. Fish and Wildlife Service lists each source as public domain. Each link opens the source photograph and its credit.

| Bird | Photographer and source |
| --- | --- |
| American avocet | [USFWS](https://www.fws.gov/media/american-avocet) |
| American robin | [Gary Kramer / USFWS](https://www.fws.gov/media/american-robin) |
| Black-necked stilt | [Lee Karney / USFWS](https://www.fws.gov/media/black-necked-stilt-3) |
| Blue jay | [Dave Menke / USFWS](https://www.fws.gov/media/blue-jay-3) |
| Cedar waxwing | [Stacey Hayden / USFWS](https://www.fws.gov/media/cedar-waxwing) |
| Northern cardinal | [Erin Huggins / USFWS](https://www.fws.gov/media/northern-cardinal-0) |
