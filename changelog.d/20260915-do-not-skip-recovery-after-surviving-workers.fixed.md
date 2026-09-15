Fixed local shutdown and recovery so leftover workers or later responses
cannot hide behind a terminal snapshot. Worker cleanup now reports whether
processes actually stopped, and recovery compares the response-table watermark.
