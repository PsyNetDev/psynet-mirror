# Use linux/amd64 platform to ensure x86_64 wheels are available (faster builds)
# On Apple Silicon Macs, Docker will emulate x86_64 but pip can use pre-built wheels
# Can be overridden with: docker build --build-arg DOCKER_PLATFORM=linux/arm64
ARG DOCKER_PLATFORM=linux/amd64
ARG PYTHON_VERSION=3.14
# Playwright needs Node 20 or later, and Node 20 reached end of life in April
# 2026. Copy the pinned Node release from the official image, built on the
# same Debian release as the Python image, instead of Debian's nodejs package.
ARG NODE_VERSION=22
FROM --platform=${DOCKER_PLATFORM} node:${NODE_VERSION}-trixie-slim AS node

FROM --platform=${DOCKER_PLATFORM} python:${PYTHON_VERSION}-trixie
ARG PYTHON_VERSION
ARG CHROME_VERSION=157.0.8103.78

# Every CI job builds this image, so a brief PyPI outage fails them all at
# once; uv's default 3 retries give up within seconds, and pip's defaults
# (15 s, 5 retries) still fail on longer blips.
RUN pip install --timeout 60 --retries 15 uv
ENV UV_HTTP_RETRIES=8

# TODO: delete some of these if we can
# fonts-liberation gives browser tests an Arial-metric font, which is what the
# participant theme's fallback face is measured against.
COPY ci/apt-get-update.sh /usr/local/bin/apt-get-update
RUN printf 'Acquire::Retries "5";\nAcquire::http::Timeout "30";\n' > /etc/apt/apt.conf.d/80-ci-network
RUN apt-get-update && timeout --kill-after=10 900 apt-get install -y curl fonts-liberation gettext jq libasound2 libatk-bridge2.0-0 libcups2 libdrm2 libdbus-1-3 libgbm1 libnss3 libpq-dev libxcomposite1 libxdamage1 libxfixes3 libxkbcommon0 libxrandr2 redis-server rsync unzip wget build-essential

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
    ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx && \
    node --version && npm --version

RUN service redis-server start
ENV HEADLESS=TRUE

# Install Chrome and ChromeDriver
RUN echo Installing Chrome $CHROME_VERSION && \
    wget -O chrome.deb https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}/linux64/chrome-linux64.zip && \
    unzip chrome.deb -d /opt/ && \
    ln -s /opt/chrome-linux64/chrome /usr/local/bin/chrome && \
    echo "Successfully installed Chrome $(chrome --version)" && \
    echo Installing ChromeDriver $CHROME_VERSION && \
    wget -O chrome-driver.zip https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}/linux64/chromedriver-linux64.zip && \
    unzip chrome-driver.zip -d /usr/local/bin/ && \
    ln -s /usr/local/bin/chromedriver-linux64/chromedriver /usr/local/bin/chromedriver && \
    echo "Successfully installed ChromeDriver $(chromedriver --version)" && \
    rm -f chrome.deb chrome-driver.zip

COPY pyproject.toml pyproject.toml
COPY ci/dallinger-dev-requirements.txt dallinger-dev-requirements.txt

# Generate PsyNet constraints.txt (experiment runtime + demos extras) and install it.
# Use a vendored Dallinger dev-requirements snapshot so parallel CI Docker
# builds do not depend on raw.githubusercontent.com availability.
# Compile for the image's full Python version: uv reads 3.11 as 3.11.0.
RUN uv pip compile --python-version "$(python -c 'import platform; print(platform.python_version())')" pyproject.toml \
        --extra experiment --extra demos \
        --constraint dallinger-dev-requirements.txt \
        --output-file constraints.txt
RUN uv pip install --no-cache --system -r constraints.txt
