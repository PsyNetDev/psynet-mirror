const path = require("path");
const { test, expect } = require("./fixtures");

test("camera video survives changes in microphone requirements @both", async ({page}) => {
  await page.route("https://capture.test/", route => route.fulfill({contentType:"text/html",body:"<main>Capture</main>"}));
  await page.route("https://capture.test/recording-capture.js", route => route.fulfill({
    contentType:"text/javascript",path:path.resolve("psynet/resources/scripts/recording-capture.js"),
  }));
  await page.goto("https://capture.test/");
  const result = await page.evaluate(async () => {
    const {RecordingDevices} = await import("/recording-capture.js");
    const devices = new RecordingDevices();
    const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    const requests = [];
    navigator.mediaDevices.getUserMedia = constraints => {
      requests.push(constraints);
      return original(constraints);
    };
    try {
      const first = await devices.acquire("camera", {audio:true});
      const microphone = first.getAudioTracks()[0];
      const silent = await devices.acquire("camera");
      const microphoneStopped = microphone.readyState === "ended" && devices.streams.get("camera").getAudioTracks().length === 0;
      const changed = await devices.acquire("camera", {audio:{channelCount:1}});
      return {
        sameVideo: [silent, changed].every(stream => stream.getVideoTracks()[0] === first.getVideoTracks()[0]),
        silent: silent.getAudioTracks().length === 0,
        microphoneStopped,
        videoRequests: requests.filter(request => request.video).length,
        microphoneRequests: requests.filter(request => request.video === false).length,
      };
    } finally {
      navigator.mediaDevices.getUserMedia = original;
      devices.release("camera");
    }
  });
  expect(result).toEqual({sameVideo:true,silent:true,microphoneStopped:true,videoRequests:1,microphoneRequests:1});
});
