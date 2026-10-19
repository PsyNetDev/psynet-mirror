Package-owned static resources
==============================

PsyNet components can be distributed in third-party Python packages. These
packages should own and publish their JavaScript, CSS, images, and other static
files rather than asking experiment authors to copy files into each
experiment's ``static`` directory.

PsyNet discovers package-owned static roots through the ``psynet.static``
Python entry-point group. Discovery happens while deployment files are
assembled, before dynamic PageMakers need to instantiate their components.

Package layout
--------------

The simplest registration uses a conventional ``static`` directory inside the
import package:

.. code-block:: text

    my_components/
        __init__.py
        controls.py
        static/
            vendor/
                chart.js
            rating-control.js
            rating-control.css

Register the import package in ``pyproject.toml``:

.. code-block:: toml

    [project.entry-points."psynet.static"]
    my-components = "my_components"

Loading this entry point imports ``my_components`` during experiment setup.
Packages with expensive or side-effectful ``__init__.py`` files should use the
callable form described below from a lightweight submodule instead.

PsyNet publishes this directory at:

.. code-block:: text

    /static/packages/my-components/

Entry-point names form URL namespaces. Dots, underscores, and hyphens are
canonicalized to lowercase hyphens, so ``my_components`` and
``my.components`` both become ``my-components`` and therefore conflict.

Using package URLs
------------------

Use :func:`psynet.static_resources.package_static_url` rather than constructing
package URLs manually:

.. code-block:: python

    from psynet.modular_page import Control
    from psynet.static_resources import package_static_url


    class RatingControl(Control):
        def get_js_dependencies(self):
            return [
                package_static_url(
                    "my-components",
                    "vendor/chart.js",
                )
            ]

        def get_js_page_modules(self):
            return [
                package_static_url(
                    "my-components",
                    "rating-control.js",
                )
            ]

The helper canonicalizes the namespace, URL-escapes safe relative paths, and
rejects absolute paths, URL schemes, backslashes, query strings, fragments, and
``..`` traversal.

Custom resource roots
---------------------

If the package cannot use the conventional ``static`` directory, its entry
point may load a callable returning another package resource root:

.. code-block:: toml

    [project.entry-points."psynet.static"]
    my-components = "my_components.assets:static_root"

.. code-block:: python

    from importlib import resources


    def static_root():
        return resources.files("my_components").joinpath("web_assets")

The callable must return a path-like resource directory supporting
``is_dir()``. Missing or invalid roots fail before deployment.

Filesystem and zip-backed packages
----------------------------------

Dallinger requires ordinary filesystem paths when collating deployment files.
If ``importlib.resources`` returns a non-filesystem Traversable, such as a
``zipfile.Path``, PsyNet copies that root into a process-lifetime temporary
directory before staging. Normal filesystem roots are used directly.

Discovery is cached for the process lifetime. Development tools or tests that
install plugins in an already running process can call
:func:`psynet.static_resources.clear_static_package_cache` to rediscover entry
points and remove materialized temporary roots. Normal deployments should
install all packages before the process starts.

Packaging requirements
----------------------

The static directory must be included in the built wheel and source
distribution. Package authors should inspect the wheel contents or install the
wheel into a clean environment as part of CI; editable installs can hide
missing build-inclusion rules.

For Hatch, a package included in the wheel normally includes its ``static``
subdirectory automatically. An explicit configuration can make the intention
clear:

.. code-block:: toml

    [tool.hatch.build.targets.wheel]
    include = ["/my_components"]

For setuptools, declare the package data:

.. code-block:: toml

    [tool.setuptools.package-data]
    my_components = ["static/**/*"]

Always inspect the built wheel, because build-backend defaults differ.

Registration and staging
------------------------

During :meth:`psynet.experiment.Experiment.extra_files`, PsyNet:

1. discovers all installed ``psynet.static`` entry points;
2. canonicalizes and sorts namespaces deterministically;
3. rejects duplicate namespaces with both distribution names;
4. imports each package or calls its root provider;
5. validates that the static root exists;
6. stages it under ``/static/packages/<namespace>``.

Registration is package-level rather than component-instance-level. This is
important because components created by dynamic PageMakers may not exist when
deployment files are collected.

Security and ownership
----------------------

Packages cannot choose arbitrary static destinations. PsyNet derives the
destination from the validated entry-point name and validates resource URLs
independently.

Installed entry-point packages are trusted Python plugins: their entry-point
module or callable executes during experiment setup. Experiments should depend
only on component packages they trust.

PsyNet's own resources
----------------------

PsyNet registers its bundled ``psynet/static`` root through the same
``psynet.static`` entry-point protocol under the ``psynet`` namespace. Existing
legacy built-in URLs remain as explicit aliases while components migrate to
namespaced package URLs. Only migrated assets live in ``psynet/static``, so the
new package mount does not duplicate PsyNet's complete legacy resource tree.
