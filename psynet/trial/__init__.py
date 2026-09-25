import os
from typing import Type

from psynet.asset import FileAsset
from psynet.trial.chain import ChainNode, ChainTrial


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
    asset_label: str = "prompt",
):
    """
    This function is used to compile nodes from a directory of media files.
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

    etc.

    You can name the participant groups, blocks and files whatever you want; the important
    thing is their position in the hierarchy.

    If you want to have this input directory inside your experiment directory,
    you should place it in the ``data`` directory.

    Otherwise, you can place it anywhere you want outside the experiment directory.

    Parameters
    ----------
    input_dir : str
        The path to the directory containing the media files.
    media_ext : str
        The extension of the media files.
    node_class : type
        The class of the node to compile.
    asset_label : str, optional
        The label of the asset to use for the media files.

    Returns
    -------
    callable
        A lambda function ready to be passed to the ``nodes`` argument of a ``TrialMaker``.
        Don't evaluate this function before you pass it, the lazy evaluation is an important feature.
    """
    return lambda: _compile_nodes_from_directory(
        input_dir, media_ext, node_class, asset_label
    )


def _compile_nodes_from_directory(
    input_dir: str,
    media_ext: str,
    node_class: Type[ChainNode],
    asset_label: str = "prompt",
):
    nodes = []
    participant_groups = [(f.name, f.path) for f in os.scandir(input_dir) if f.is_dir()]
    for participant_group, group_path in participant_groups:
        blocks = [(f.name, f.path) for f in os.scandir(group_path) if f.is_dir()]
        for block, block_path in blocks:
            media_files = [
                (f.name, f.path)
                for f in os.scandir(block_path)
                if f.is_file() and f.path.endswith(media_ext)
            ]
            for media_name, media_path in media_files:
                nodes.append(
                    node_class(
                        definition={
                            "name": media_name,
                        },
                        assets={
                            asset_label: FileAsset(
                                input_path=media_path,
                                extension=media_ext,
                            )
                        },
                        participant_group=participant_group,
                        block=block,
                    )
                )
    return nodes
