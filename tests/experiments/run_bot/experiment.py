import tempfile

import psynet.experiment
from psynet.modular_page import (
    AudioRecordControl,
    ModularPage,
    TextControl,
    VideoRecordControl,
)
from psynet.timeline import (
    Timeline,
)


class Exp(psynet.experiment.Experiment):
    label = "Run bot test"

    timeline = Timeline(
        ModularPage(
            "favourite_colour",
            "What's your favourite colour?",
            TextControl(bot_response="red"),
            time_estimate=5,
        ),
        ModularPage(
            "record_audio",
            "Please speak your name into the microphone.",
            AudioRecordControl(
                duration=5.0,
                bot_response_media=lambda bot: generate_media_file(
                    "wav", f"This is a recording from {bot.id}!"
                ),
            ),
            time_estimate=5,
        ),
        ModularPage(
            "record_video",
            "We'll now make a recording of your screen and camera.",
            VideoRecordControl(
                duration=5.0,
                recording_source="both",
                show_preview=True,
                controls=True,
                bot_response_media=lambda bot: {
                    "camera": generate_media_file(
                        "webm", f"This is a camera recording from bot {bot.id}."
                    ),
                    "screen": generate_media_file(
                        "webm", f"This is a screen recording from bot {bot.id}."
                    ),
                },
            ),
            time_estimate=5,
        ),
    )


# Uploads are checked for a media header, not decoded, so a header followed by
# text lets the test identify each bot's file.
MEDIA_HEADERS = {
    "wav": b"RIFF\x00\x00\x00\x00WAVE",
    "webm": b"\x1a\x45\xdf\xa3",
}


def generate_media_file(media_format: str, text: str):
    """
    Generates a small file with a valid media header to test bot uploads.

    Returns
    -------
    str
        Path to the generated file.
    """
    with tempfile.NamedTemporaryFile(
        suffix=f".{media_format}", delete=False, mode="wb"
    ) as tmpfile:
        tmpfile.write(MEDIA_HEADERS[media_format] + text.encode())
        file_path = tmpfile.name

    return file_path
