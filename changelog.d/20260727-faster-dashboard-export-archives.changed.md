Dashboard export archives now use ZIP_STORED for already-compressed file types
(media, images, nested ZIPs) and ZIP_DEFLATED for text formats, removing
redundant DEFLATE overhead on the dashboard download path. The dashboard and
automatic backup write ``export.zip`` beside a temporary export tree rather than
into the process working directory. Dashboard downloads keep that tree until the
file response has been sent.
