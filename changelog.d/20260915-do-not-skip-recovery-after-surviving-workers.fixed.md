Fixed local shutdown and recovery so leftover workers or later responses
cannot hide behind a terminal snapshot. Worker cleanup now reports whether
processes actually stopped. Recovery compares the response-table watermark
taken in the same database transaction as the archive, and does not skip
when that watermark cannot be read.
