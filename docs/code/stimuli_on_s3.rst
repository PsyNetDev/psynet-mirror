.. _large_stimulus_sets:

Hosting stimuli on S3
=====================

Stimulus sets larger than the deployment size limit (see
:doc:`/deploy/how_deployment_works`) can be hosted in an Amazon Web
Services S3 bucket and linked into the experiment by URL. The examples use
the bucket ``my-bucket`` and the key (subdirectory) ``my-key``.

1. Install the `AWS CLI
   <https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html>`_,
   check the installation with ``aws --version``, and set up credentials
   with ``aws configure``.

2. Create the bucket, unless it already exists:

   .. code-block:: bash

       aws s3 mb s3://my-bucket

3. Upload the folder of files and list the result:

   .. code-block:: bash

       cd ~/my-audio-files/
       aws s3 cp . s3://my-bucket/my-key/ --recursive
       aws s3 ls s3://my-bucket/my-key/

   .. warning::
       Spaces and special characters in file names can break the URLs. Use
       only lowercase Latin letters (``a-z``), digits, underscores (``_``) and
       hyphens (``-``).

4. Allow public bucket policies. New buckets block them by default, so the
   next step fails until this setting is changed:

   .. code-block:: bash

       aws s3api put-public-access-block --bucket my-bucket \
           --public-access-block-configuration \
           "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=false,RestrictPublicBuckets=false"

   If Block Public Access is also turned on for the whole AWS account, it
   takes precedence and must be turned off there as well.

5. Allow public read access to the key with a bucket policy. Save the
   following as ``my-policy.json``:

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

   and apply it:

   .. code-block:: bash

       aws s3api put-bucket-policy --bucket my-bucket --policy file://my-policy.json

   The files are then available at URLs such as
   ``https://my-bucket.s3.amazonaws.com/my-key/my-file.wav``.

6. Allow cross-origin requests with a CORS policy. Save the following as
   ``my-cors.json``:

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

   and apply it:

   .. code-block:: bash

       aws s3api put-bucket-cors --bucket my-bucket --cors-configuration file://my-cors.json

7. List the file names in a text file in the experiment directory. Filtering
   by extension leaves out other files, such as the ``.DS_Store`` files
   created by macOS:

   .. code-block:: bash

       ls ~/my-audio-files/*.wav | xargs -n 1 basename > stimuli.txt

8. Create one node per file in ``experiment.py``:

   .. code-block:: python

       from psynet.modular_page import AudioPrompt, ModularPage, PushButtonControl
       from psynet.trial.static import StaticNode, StaticTrial

       S3_BUCKET = "my-bucket"
       S3_KEY = "my-key"


       def get_s3_url(stimulus):
           return f"https://{S3_BUCKET}.s3.amazonaws.com/{S3_KEY}/{stimulus}"


       with open("stimuli.txt", "r") as f:
           stimuli = f.read().splitlines()

       nodes = [
           StaticNode(definition={"url": get_s3_url(stimulus)})
           for stimulus in stimuli
       ]


       class AudioRatingTrial(StaticTrial):
           time_estimate = 5

           def show_trial(self, experiment, participant):
               return ModularPage(
                   "audio_rating",
                   AudioPrompt(self.definition["url"], "How much do you like this song?"),
                   PushButtonControl(["Not at all", "A little", "Very much"]),
               )

The URLs can also be registered as assets, with
``asset("https://my-bucket.s3.amazonaws.com/my-key/my-file.wav")`` or
:class:`~psynet.asset.ExternalS3Asset`. PsyNet then lists them in the
database and export metadata, but does not upload, copy or export the files.
Attach them to nodes as described in :doc:`/code/trials/assets`.
