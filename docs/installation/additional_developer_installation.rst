.. _additional_developer_installation:

Additional developer installation steps
---------------------------------------

These are some additional steps you should take if you plan to contribute
to PsyNet's source code and you are using the virtual environment installation method.


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

Download Dallinger and PsyNet
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Download Dallinger from GitHub:

.. code-block:: bash

    cd
    git clone https://github.com/Dallinger/Dallinger

If you haven't already done so, download PsyNet from GitLab:

.. code-block:: bash

    cd
    git clone https://gitlab.com/PsyNetDev/PsyNet

Open PsyNet in your IDE
~~~~~~~~~~~~~~~~~~~~~~~~

Open the PsyNet folder (the folder you downloaded from GitLab) in your IDE.
Use your IDE to create a virtual environment for PsyNet, using the Python version specified
in ``pyproject.toml``.

Install PsyNet and Dallinger in editable mode
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Within the virtual environment you just created, install PsyNet and Dallinger in editable mode:

.. code-block:: bash

    cd ~/Dallinger
    pip3 install --editable ".[data]"
    cd ~/Psynet
    pip3 install --editable ".[dev]"

Editable mode means that any changes you make to the
Dallinger/PsyNet source code will be automatically reflected in your virtual environment.

You can then check your installation by running

.. code-block:: bash

    psynet --version

.. note::

    When you are developing in PsyNet/Dallinger it's important to keep track of which versions of the packages
    you need. Particular versions of PsyNet are tied to particular versions of Dallinger.
    To switch to a particular version of Dallinger or PsyNet, navigate to the relevant directory and run
    ``git checkout <tag>`` where ``<tag>`` is the version you want to use. For example:

    .. code-block:: bash

       cd ~/Dallinger
       git checkout v9.0.0
       cd ~/PsyNet
       git checkout v10.1.0


Install the Git pre-commit hook
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

With the virtual environment still activated:

.. code-block:: bash

   pip3 install pre-commit
   pre-commit install

This will install the pre-commit hooks defined in ``.pre-commit-config.yaml`` to lint, sort imports,
and format Python code using `ruff <https://docs.astral.sh/ruff/>`__.
You can run the Ruff checks manually at any time by running:

.. code-block:: bash

   pre-commit run --all-files

You may also want to install Ruff support for your own code editor, though this is not strictly necessary,
since the pre-commit hook will run Ruff for you on commit.
