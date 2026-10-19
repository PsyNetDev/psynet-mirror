SSH exports now establish one SSH connection and reuse it for every step, rather
than opening a separate connection to probe for rsync, to look up the remote home
directory, and to fetch `logs.jsonl`. Each connection cost a full handshake, which
was a noticeable share of the runtime for a small or fully cached export.
