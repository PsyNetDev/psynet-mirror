.. _additional_developer_installation:

Setting up a development checkout
---------------------------------


Add your SSH key to GitLab
~~~~~~~~~~~~~~~~~~~~~~~~~~

If you don't yet have a GitLab user account, please create one via the GitLab website.
You need to generate an SSH key (if you don't have one already) and upload it to GitLab.

To generate an SSH key:

.. code-block:: bash

   ssh-keygen -b 4096 -t rsa

Press Enter to save the key in the default location,
and Enter again twice to create the key with no passphrase.

Copy the SSH key to the clipboard by running this command:

.. code-block:: bash

   pbcopy < ~/.ssh/id_rsa.pub

On Linux you can print the key and copy it manually:

.. code-block:: bash

   cat ~/.ssh/id_rsa.pub

On WSL you can also copy it directly to the Windows clipboard:

.. code-block:: bash

   cat ~/.ssh/id_rsa.pub | clip.exe

Then add the key in GitLab under **User settings → SSH Keys**.
See `GitLab's SSH documentation <https://docs.gitlab.com/user/ssh/>`_
for the current steps. Paste the key in the 'Key' box,
remove the Expiration date if you think it's helpful, then click 'Add key'.

Install ChromeDriver
~~~~~~~~~~~~~~~~~~~~

Needed for running the Selenium tests with headless Chrome.

.. note::

   The version of ChromeDriver *must* match the version of Chrome you have currently installed.

On macOS run this line

.. code-block:: bash

    brew install chromedriver

For Linux or Windows

    Navigate to `Chrome for Testing <https://googlechromelabs.github.io/chrome-for-testing/#stable>`_ to find the download link for ChromeDriver corresponding to your Chrome installation. Copy the link and use it to download and then unzip the ChromeDriver executable, e.g. on Linux:

    .. code-block:: bash

        wget https://edgedl.me.gvt1.com/edgedl/chrome/chrome-for-testing/121.0.6167.85/linux64/chromedriver-linux64.zip --directory /tmp
        sudo unzip -j /tmp/chromedriver-linux64.zip 'chromedriver-linux64/chromedriver' -d /usr/local/bin

.. note::

    *MacOS users only*:

    By default chromedriver will be blocked by the MacOS security policy.
    To unblock it, first try to run it:

    .. code-block:: bash

       chromedriver --version

    If you see an error message stating that Apple cannot check chromedriver for malicious software,
    you can disable it by going to System Settings, Privacy & Security,
    then looking for a line that says '"Chromedriver was blocked from use because it is not from an
    identified developer"'. Click 'Allow anyway', then try rerunning Chromedriver.

Clone PsyNet and Dallinger
~~~~~~~~~~~~~~~~~~~~~~~~~~

Follow :doc:`/install` for the system tools (uv, Git, Docker, Chrome and
the Heroku CLI), then clone both repositories next to each other:

.. code-block:: bash

    cd
    git clone https://gitlab.com/PsyNetDev/PsyNet
    git clone https://github.com/Dallinger/Dallinger

Create the development environment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Create a virtual environment in the PsyNet checkout and install PsyNet in
editable mode with its development extras. uv installs the Python version
that PsyNet requires.

.. code-block:: bash

    cd ~/PsyNet
    uv venv --python 3.14
    source .venv/bin/activate
    uv pip install -e ".[dev,demos,slack]"
    psynet --version

If you are changing Dallinger as well, install your checkout in editable mode
into the same environment:

.. code-block:: bash

    uv pip install -e ~/Dallinger

Editable mode means that changes to the PsyNet or Dallinger source are used
immediately. Particular PsyNet versions need particular Dallinger versions:
to work on an older release, check out its tag in both repositories, taking
the Dallinger version from that tag's ``pyproject.toml``.

Start PostgreSQL and Redis for local runs and tests:

.. code-block:: bash

    psynet services ensure

Install the Git pre-commit hook
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``pre-commit`` is part of the ``dev`` extras. Install the hook, which lints
and formats code with `ruff <https://docs.astral.sh/ruff/>`__ on every commit:

.. code-block:: bash

    pre-commit install

Run the same checks on the whole repository at any time with:

.. code-block:: bash

    pre-commit run --all-files
