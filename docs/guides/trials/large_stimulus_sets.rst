.. _large_stimulus_sets:

===================
Large stimulus sets
===================

PsyNet users often want to run experiments that involve a large number of pregenerated
multimedia files (e.g. images, audio, or video). It is possible to implement such experiments
using PsyNet's asset management system, but this system currently has some performance overhead
that can make such experiments slow to deploy.

This tutorial explains an alternative approach that sidesteps these problems. Here the files
are instead hosted on Amazon Web Service's S3 Storage service, and linked into the experiment
using custom code.

Getting started
---------------

1. The first step is to install the `AWS client <https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html>`_
2. Now check it's installed properly by running ``aws --version`` in your terminal.
3. Now open another terminal window and move to the audio directory you want to upload, e.g. ``cd ~/my-audio-files/``

.. warning::
    Make sure your filenames don't contain spaces or special characters which can break the URL. The best practice is to only use lower case latin characters (``a-z``), underscores (``_``) and hyphens (``-``).

4. Now upload the files to a S3 bucket and key (subdirectory) of your choice, e.g. ``aws s3 cp . s3://my-bucket/my-key/`` which will upload all files in the current directory to the bucket ``my-bucket`` and key ``my-key``.
5. This will take a while if you have a lot of files. Once this is done, you can list the files by running ``aws s3 ls s3://my-bucket/my-key/`` in your terminal.
6. Now create a bucket policy file, e.g. ``my-policy.json``, which allows public access to the files.
   You can initialize the file by writing ``touch my-policy.json`` in your terminal.
   Open this file in your text editor and paste the following policy:

.. code-block:: json

    {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "PublicReadGetObject",
                "Effect": "Allow",
                "Principal": "*",
                "Action": "s3:GetObject",
                "Resource": "arn:aws:s3:::my-bucket/my-key/*"
            }
        ]
    }

7. You now need to apply this policy to your bucket. Run the following command in your terminal:

.. code-block:: bash

    aws s3api put-bucket-policy --bucket my-bucket --policy file://my-policy.json

8. Now you should be able to access the files by their URL, e.g. ``https://my-bucket.s3.amazonaws.com/my-key/my-file.wav``

9. You also need to set the bucket's CORS policy to allow cross-origin requests.
   You can define this policy by creating a file called ``my-cors.json`` and pasting the following into it:

.. code-block:: json

    [
        {
            "AllowedHeaders": ["*"],
            "AllowedMethods": ["GET"],
            "AllowedOrigins": ["*"],
            "ExposeHeaders": [],
            "MaxAgeSeconds": 3000
        }
    ]

10. You can apply this policy by running the following command in your terminal:

.. code-block:: bash

    aws s3api put-bucket-cors --bucket my-bucket --cors-configuration file://my-cors.json

11. You can now make a text file which contains the filenames of the files by running ``ls > stimuli.txt`` in your terminal.

.. note::
    It can be useful to filter by the file extension, e.g. ``ls *.wav > stimuli.txt``.
    This makes sure you don't include any files that are not audio files in the text file,
    for example ``.DS_Store`` files which are created by macOS.

12. Now you can create nodes from the text file, e.g.:

.. code-block:: python

    from psynet.trial.static import StaticNode, StaticTrial
    from psynet.modular_page import AudioPrompt, PushButtonControl, ModularPage

    S3_BUCKET = "my-bucket"
    S3_KEY = "my-key"

    def get_s3_url(stimulus):
        return f"https://{S3_BUCKET}.s3.amazonaws.com/{S3_KEY}/{stimulus}"

    with open("stimuli.txt", "r") as f:
        stimuli = f.read().splitlines()

    nodes = [
        StaticNode(
            definition={"url": get_s3_url(stimulus)},
        )
        for stimulus in stimuli
    ]

    class AudioRatingTrial(StaticTrial):
        time_estimate = 5

        def show_trial(self, experiment, participant):
            return ModularPage(
                "audio_rating",
                AudioPrompt(
                    self.node.definition["url"],
                    "How much do you like this song?",
                ),
                PushButtonControl(
                    ["Not at all", "A little", "Very much"],
                ),
            )
