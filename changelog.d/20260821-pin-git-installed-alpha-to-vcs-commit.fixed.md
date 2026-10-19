Fixed ``psynet setup`` pinning a GitLab/git install of an unpublished alpha
as ``psynet[experiment]==13.4.0a0``, which cannot be resolved from PyPI.
Standalone experiments now reuse the installed VCS commit
(``psynet[experiment] @ git+<url>@<commit>``) when compiling constraints.
