# Which way is the bird facing?

Run `psynet debug local` in this directory, from a PsyNet source checkout. Press the left or right arrow key to say which way each bird's beak points. Each of the six birds appears once, in a shuffled order, and the final page scores your six answers.

## How the photographs are loaded in advance

1. In [experiment.py](experiment.py), `preload_fields = ("bird",)` sends the participant's sequence of bird IDs to the browser. The correct directions stay on the server.
2. The page lists its six JPEGs in `MediaSpec(image=...)`. Each ID matches a hidden `<img>` element on the page, and PsyNet points that element at the downloaded file.
3. When the page starts, [birds.js](static/birds.js) waits for all six images to decode. Moving to the next bird then only hides one image and shows another. As in the arrow flanker demo, the page calls `game.startResponseClock(view)` in the frame that shows each photograph and `response.answer(value)` when a key is pressed.

To watch this happen, open the **Network** panel of your browser's developer tools on the instruction page. Disable the cache, choose a slow connection and filter for `/static/birds/`, then press **Next**. All six JPEGs download before the first bird appears, and no more requests appear as you play. If you reload the game page, it downloads the images again and continues from the first unanswered bird.

The [arrow flanker](../live_trial_game) is the same kind of task with text instead of images. For a long sequence of images, see [VocabTest's page script](../../../psynet/resources/scripts/vocabtest.js), which downloads only the next few.

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
