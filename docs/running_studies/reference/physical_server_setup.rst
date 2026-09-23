.. _physical_server_setup:

============================
Setting up a physical server
============================

This page provides guidelines for setting up a physical server
to run PsyNet-based experiments. It covers hardware recommendations,
software requirements, and essential networking configurations.
Thank you Manuel Anglada-Tort for compiling this content.

Why use a physical server?
--------------------------

Advantages
^^^^^^^^^^

* **Long-term cost savings**: A one-time hardware purchase can eliminate ongoing AWS (or other cloud) costs.

* **Full control over hardware and configuration**: Avoid dependency on external cloud services or third-party virtualization layers.

* **Local performance advantages**: Running complex experiments or handling sensitive data can be more straightforward on local infrastructure.

Disadvantages
^^^^^^^^^^^^^

* **Onsite management required**: Physical servers must be maintained on-premises, including dealing with power cuts and physical restarts.

* **IT support and firewall policies**: Coordinating with institutional IT might be more involved than using cloud services.

Recommended hardware specifications
-----------------------------------

Note: the following recommendations were compiled in late 2024. As time goes on,
available hardware will improve and the best options may change.

* **Processor**: A modern multi-core CPU (e.g., 16-core AMD Ryzen) for running multiple experiments concurrently.

* **Memory (RAM)**: At least 32GB of RAM to ensure smooth performance, especially if running multiple containers or experiments at once.

* **Storage**:

  * Primary Drive: SSD (e.g., NVMe) for the operating system and experiment code (1TB).
  * Secondary Drive: Another SSD for databases and data storage for faster access (4TB).

* **GPU**: A basic GPU or integrated graphics are sufficient for PsyNet.

Choosing an AM5 system (if using AMD processors) is recommended but ultimately, the exact specs can vary. Focus on a reliable CPU, ample RAM, and fast storage.

Software requirements
---------------------

What to install on the server
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

PsyNet's deployment system automates most installations. The following are the primary requirements:

Operating system
""""""""""""""""
* Ubuntu 22.04 LTS or Ubuntu 24.04 LTS (recommended) or Windows 11 Pro

Dependencies
""""""""""""
* PsyNet handles installing Docker and other required software automatically
* No need to manually install Python, PostgreSQL, or Nginx

User privileges
"""""""""""""""
* The server account should have sudo privileges to allow PsyNet to manage installations

SSH configuration
"""""""""""""""""
* Enable passwordless SSH access using key-based authentication

Networking configuration
------------------------

Firewall settings
^^^^^^^^^^^^^^^^^

SSH access (Port 22)
"""""""""""""""""""""
* Restrict SSH access to internal networks or via a VPN
* Ensure SSH is firewalled from external access for security

HTTPS access (Port 443)
"""""""""""""""""""""""
* PsyNet uses port 443 for serving experiments over HTTPS
* The firewall must allow incoming HTTPS traffic from anywhere

Reverse proxy consideration
"""""""""""""""""""""""""""
* PsyNet uses Caddy as a built-in reverse proxy to handle HTTPS
* If direct access through the firewall is restricted, coordinate with IT to use an institutional reverse proxy

DNS configuration
^^^^^^^^^^^^^^^^^
* Assign a wilcard domain name (e.g., \*.psynet.experiment.gold.ac.uk) that points to the server's IP address
* Ensure DNS entries are set up to route external traffic correctly

SSL certificates
^^^^^^^^^^^^^^^^
* PsyNet automatically provisions SSL/TLS certificates via Caddy and Let's Encrypt
* No manual SSL setup is needed
