
WSL 2 installation is incomplete
--------------------------------

If you see a message beginning with "WSL 2 installation is incomplete", you probably need to do the following:

- Click on the link it gives you
- Click on the link under 'download the latest package', open and run the installer once it has downloaded
- Continue with the next steps of the installation
- Note: if you run Powershell, it might fail if you run it on admin mode! If you get stuck (Access Denied),
  try running it again without admin mode and see if it works.

Hardware assisted virtualization
--------------------------------

If you see a message beginning "Hardware assisted virtualization and data execution protection must be enabled in the
BIOS", you need to restart your computer into BIOS and change some settings to enable those two things. The precise set
of steps will depend on your computer. The first step though is to restart your computer, and press a certain key to
launch into BIOS -- ordinarily that key will be printed on the screen at some point during the startup sequence.
Hint -- you might find that the option you need to select is called 'SVM mode'...

Audio or microphone not available in WSL
----------------------------------------

On Windows 11 with WSLg, audio and microphone support should work out of the box.
If you still cannot access audio devices from WSL, you can try a legacy PulseAudio bridge:

1. Download ``pulseaudio-windows`` from http://bosmans.ch/pulseaudio/pulseaudio-1.1.zip and unzip it.
2. In ``etc/pulse/default.pa``, uncomment or add the following line:

   .. code-block:: text

      load-module module-native-protocol-tcp auth-anonymous=1

3. In ``etc/pulse/daemon.conf``, set ``exit-idle-time = -1``.
4. Start ``pulseaudio.exe`` from the unzipped folder on Windows.
5. In your Ubuntu (WSL) terminal, run:

   .. code-block:: bash

      sudo apt install -y libasound2-plugins pulseaudio

.. note::

   The PulseAudio bridge enables anonymous local connections. Use it only on trusted machines.
