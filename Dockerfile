# Use linux/amd64 platform to ensure x86_64 wheels are available (faster builds)
# On Apple Silicon Macs, Docker will emulate x86_64 but pip can use pre-built wheels
# Can be overridden with: docker build --build-arg DOCKER_PLATFORM=linux/arm64
ARG DOCKER_PLATFORM=linux/amd64
ARG PYTHON_VERSION=3.13
FROM --platform=${DOCKER_PLATFORM} python:${PYTHON_VERSION}-bookworm
ARG PYTHON_VERSION
ARG CHROME_VERSION=149.0.7827.54

RUN pip install uv

# TODO: delete some of these if we can
RUN apt-get update && apt-get install -y curl gettext jq libasound2 libatk-bridge2.0-0 libcups2 libdrm2 libdbus-1-3 libgbm1 libnss3 libpq-dev libxcomposite1 libxdamage1 libxfixes3 libxkbcommon0 libxrandr2 redis-server unzip nodejs npm wget build-essential

# Heroku CLI is currently needed to run `psynet test local`, this should change soon
RUN curl --fail --location --show-error --retry 5 --retry-connrefused --retry-delay 2 \
        --output /tmp/heroku-install.sh https://cli-assets.heroku.com/install.sh && \
    sh /tmp/heroku-install.sh && \
    rm /tmp/heroku-install.sh && \
    heroku --version
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
RUN uv pip compile --python-version ${PYTHON_VERSION} pyproject.toml \
        --extra experiment --extra demos \
        --constraint dallinger-dev-requirements.txt \
        --output-file constraints.txt
RUN uv pip install --no-cache --system -r constraints.txt
