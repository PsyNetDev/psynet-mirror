# Arrow flanker

Run `psynet debug local` in this directory. Use the left and right arrow keys to match the **middle** arrow. The round shuffles two copies of four patterns and presents all eight on one page. A brief blank separates successive patterns, including identical ones.

In the debug dashboard, inspect the trial table when the first pattern appears. All eight rows already have a node and a position. Answer three, wait for those rows to be marked complete, then reload the participant page. You should see the fourth pattern again. Finish the round and compare the feedback with the sum of the eight trial scores. Each row also holds the direction pressed and the time in seconds from the latest display of the pattern to the keypress.

[experiment.py](experiment.py) defines the nodes, scores the native trials and reads them back for feedback. [flanker.js](static/flanker.js) presents the next prepared pattern immediately while PsyNet saves the response.

## Extending this to images

`preload_fields` sends the public stimulus fields for the planned trials to the browser. For images, sending a URL prepares the deck; the browser still has to fetch and decode the pixels. For a small fixed set, declare the images in the game page’s `media=MediaSpec(image=...)`; the [graphics demo](../../experiments/graphics/experiment.py) shows how to declare page media. For a longer, participant-specific deck, see [VocabTest’s browser module](../../../psynet/resources/scripts/vocabtest.js) for a working example. It starts fetching the next two images while the participant answers and awaits `decode()` before showing an image and starting its response clock.
