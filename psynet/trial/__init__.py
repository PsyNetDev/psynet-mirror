from pathlib import Path
from typing import Type

from psynet.trial.chain import ChainNode, ChainTrial

__all__ = [
    "Trial",
    "Node",
    "compile_nodes_from_directory",
]


class Trial(ChainTrial):
    pass


class Node(ChainNode):
    pass

    def summarize_trials(self, trials: list, experiment, participant):
        return None

    def create_definition_from_seed(self, seed, experiment, participant):
        return None


def compile_nodes_from_directory(
    input_dir: str,
    media_ext: str,
    node_class: Type[ChainNode],
    url_key: str = "url",
):
    """Compile trial nodes from a directory of media files under ``static/``.

    This directory is expected to be structured in the following kind of way:

    input_dir/
    |-- participant_group_1/
    |   |-- block_1/
    |   |   |-- media_file_1.wav
    |   |   |-- media_file_2.wav
    |   |-- block_2/
    |   |   |-- media_file_3.wav
    |   |   |-- media_file_4.wav
    |   |-- block_3/
    |   |   |-- media_file_5.wav
    |   |   |-- media_file_6.wav
    |-- participant_group_2/
    |   |-- block_1/
    |   |   |-- media_file_7.wav
    |   |   |-- media_file_8.wav
    |   |-- block_2/
    |   |   |-- media_file_9.wav
    |   |   |-- media_file_10.wav
    |   |-- block_3/

    You can name the participant groups, blocks and files whatever you want; the important
    thing is their position in the hierarchy.

    Place ``input_dir`` under the experiment ``static/`` directory so the files
    are copied with the deployment plan and served as ``/static/...`` URLs.
    Paths outside ``static/`` (including directories outside the experiment)
    are not supported. Each node definition stores that URL under ``url_key``
    (default ``"url"``). Pass ``self.definition[url_key]`` to ``AudioPrompt``.
    Participant groups, blocks, and files are visited in alphabetical order
    by name.

    Parameters
    ----------
    input_dir : str
        The path to the directory containing the media files.
    media_ext : str
        The extension of the media files.
    node_class : type
        The class of the node to compile.
    url_key : str, optional
        Key in the node definition that stores the media URL.

    Returns
    -------
    callable
        A lambda function ready to be passed to the ``nodes`` argument of a ``TrialMaker``.
        Don't evaluate this function before you pass it, the lazy evaluation is an important feature.
    """
    return lambda: _compile_nodes_from_directory(
        input_dir, media_ext, node_class, url_key
    )


def _compile_nodes_from_directory(
    input_dir: str,
    media_ext: str,
    node_class: Type[ChainNode],
    url_key: str = "url",
):
    from psynet.media import static_url_for

    static_url_for(input_dir)
    nodes = []
    input_path = Path(input_dir)
    if not input_path.is_dir():
        raise FileNotFoundError(
            f"compile_nodes_from_directory: {input_dir!r} is not a directory."
        )
    suffix = media_ext.lower()
    if not suffix.startswith("."):
        suffix = f".{suffix}"
    for group_dir in _sorted_subdirectories(input_path):
        for block_dir in _sorted_subdirectories(group_dir):
            media_files = sorted(
                (
                    path
                    for path in block_dir.iterdir()
                    if path.is_file() and path.suffix.lower() == suffix
                ),
                key=lambda path: path.name,
            )
            for media_path in media_files:
                nodes.append(
                    node_class(
                        definition={
                            "name": media_path.name,
                            url_key: static_url_for(media_path),
                        },
                        participant_group=group_dir.name,
                        block=block_dir.name,
                    )
                )
    return nodes


def _sorted_subdirectories(path: Path):
    return sorted(
        (child for child in path.iterdir() if child.is_dir()),
        key=lambda child: child.name,
    )
