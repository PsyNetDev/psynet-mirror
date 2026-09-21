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

ENV SKIP_DEPENDENCY_CHECK=""
ENV DALLINGER_NO_EGG_BUILD=1

RUN if [ -f constraints.txt ]; then \
        uv pip install -r constraints.txt --system; \
    else \
        uv pip install -r requirements.txt --system; \
    fi

COPY *prepare_docker_image.sh prepare_docker_image.sh
RUN if test -f prepare_docker_image.sh ; then bash prepare_docker_image.sh ; fi

COPY . /experiment

# A local Dallinger wheel staged by ``DALLINGER_SOURCE`` / editable install
# must win over the Git pin installed from requirements/constraints above.
RUN set -- /experiment/dallinger-*.whl; \
    if [ -f "$1" ]; then \
        uv pip install --system --force-reinstall --no-deps "$1"; \
    fi

ENV PORT=5000

CMD dallinger_heroku_web
