
Quick start (Windows 11)
------------------------
1. Press Win + R, type ``cmd``, and press Enter.
2. Run ``wsl --install`` (this installs WSL 2 and the default Ubuntu distro).
   If you already have WSL installed but no Ubuntu distro, run ``wsl --install -d Ubuntu``.
3. Restart your computer if prompted.
4. Launch Ubuntu from the Start menu, or run ``wsl -d Ubuntu``.
5. Create a username and password when prompted.
6. Verify or set Ubuntu as the default distro (see commands below).

For a more detailed walkthrough, see:
https://ubuntu.com/wsl/docs/stable/howto/install-ubuntu-wsl2/.
Note: it is WSL 2 we want, not just WSL. Bear this in mind when looking for online tutorials.

WSL is a platform for installing particular Linux operating systems. In addition to installing WSL,
the above tutorial also installs Ubuntu, which is a particular flavor of the Linux operating system.
This is important for getting Docker to work.

Once you've installed Ubuntu, it's important that you select it as the default distro within WSL.
You can list available distros within WSL by running the following command in your terminal:

::

    wsl -l --all

You want to set your default to the Ubuntu option.
That probably means writing something like this:

::

    wsl --setdefault Ubuntu


Note: If you see a message beginning "Hardware assisted virtualization and data execution protection
must be enabled in the BIOS", you need to restart your computer into BIOS and change some settings to enable those two things.
The precise set of steps will depend on your computer. The first step though is to restart your computer,
and press a certain key to launch into BIOS -- ordinarily that key will be printed on the screen at some point
during the startup sequence. Hint -- you might find that the option you need to select is called 'SVM mode'....
