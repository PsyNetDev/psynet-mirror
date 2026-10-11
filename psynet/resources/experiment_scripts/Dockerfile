# This Dockerfile is used both to specify a functional development environment
# (e.g. on GitHub Codespaces) and a deployment image.

FROM python:3.13-bookworm

RUN pip install uv


# This is necessary for installing Heroku CLI. Remove it once we remove Heroku.
# Heroku CLI is currently needed to run `psynet test local`, this should change soon
RUN apt-get update && apt-get install -y nodejs npm
RUN curl https://cli-assets.heroku.com/install.sh | sh

RUN mkdir /experiment
WORKDIR /experiment

COPY requirements.txt requirements.txt
COPY *constraints.txt constraints.txt

# Local PsyNet and Dallinger wheels, staged by ``psynet debug ssh
# --use-local-psynet`` and ``--use-local-dallinger``, are installed further
# down. Their packages' own pins are skipped here, because an editable pin
# points at a checkout that only exists on the developer's machine.
COPY psynet-*.whl dallinger-*.whl ./

ENV SKIP_DEPENDENCY_CHECK=""
ENV DALLINGER_NO_EGG_BUILD=1

RUN pins=requirements.txt; \
    if [ -f constraints.txt ]; then pins=constraints.txt; fi; \
    for package in psynet dallinger; do \
        if ls "$package"-*.whl >/dev/null 2>&1; then \
            grep -viE "^[^#]*(^|[^[:alnum:]_-])$package([^[:alnum:]_-]|$)" \
                "$pins" > "/tmp/$package-pins.txt"; \
            pins="/tmp/$package-pins.txt"; \
        fi; \
    done; \
    uv pip install -r "$pins" --system

COPY *prepare_docker_image.sh prepare_docker_image.sh
RUN if test -f prepare_docker_image.sh ; then bash prepare_docker_image.sh ; fi

COPY . /experiment

# ``psynet debug ssh --use-local-psynet`` stages a wheel of the local PsyNet
# checkout, which replaces the requirements.txt version.
RUN set -- /experiment/psynet-*.whl; \
    if [ -f "$1" ]; then \
        uv pip install --system --reinstall-package psynet "psynet[experiment] @ file://$1"; \
    fi

# A local Dallinger wheel staged by ``DALLINGER_SOURCE`` / editable install
# must win over the Git pin installed from requirements/constraints above.
RUN set -- /experiment/dallinger-*.whl; \
    if [ -f "$1" ]; then \
        uv pip install --system --force-reinstall --no-deps "$1"; \
    fi

# The SSH account is chosen when the container starts. These directories must
# be writable so that account can create server.log and the static/assets link.
# Shipped source files stay owned by root.
RUN mkdir -p /experiment/static \
 && chmod a+rwx /experiment /experiment/static

ENV PORT=5000

CMD dallinger_heroku_web
