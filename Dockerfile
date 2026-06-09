ARG REGISTRY="docker.io/library"
ARG BUILD_IMAGE='python'
ARG BUILD_TAG='3.12-trixie'
ARG BASE_IMAGE='python'
ARG BASE_TAG='3.12-slim-trixie'

FROM dhi.io/python:3.12-debian-dev AS builder
ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_DISABLE_PIP_VERSION_CHECK=yes
ARG PIP_CERT
ARG PIP_CLIENT_CERT
ARG PIP_TRUSTED_HOST
ARG PIP_INDEX_URL
ARG PIP_EXTRA_INDEX_URL
ARG GIT_BRANCH_NAME
# expected to be public registry (e.g pypi.org)
ARG UV_DEFAULT_INDEX
# expected to be private registry
ARG UV_INDEX_URL
ARG UV_INSECURE_HOST
# Ensure uv installs to the correct directory
ENV UV_PROJECT_ENVIRONMENT=/usr/local

COPY debian.txt /tmp/src/
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
    $(grep -vE "^\s*(#|$)" /tmp/src/debian.txt | tr "\n" " ") && \
    rm -rf /tmp/src/debian.txt /var/lib/apt/lists/*

# copy all files not in .dockerignore
COPY ./ /tmp/src
RUN pip install uv

# build and install package
WORKDIR /tmp/src
# Install all dependencies
RUN uv sync --frozen --no-editable --group plugins
# Install package with version attached. (hatchling and hatch-vcs installed after sync to avoid being uninstalled)
RUN uv pip install --system hatchling hatch-vcs
RUN uv build . --out-dir /tmp/
RUN uv pip uninstall --system azul-restapi-server
RUN uv pip install --system --no-deps --find-links /tmp/ azul-restapi-server==$(hatchling version)

# Upgrade to dev azul dependencies or upgrade non-dev azul dependencies depending on branch.
RUN if [ "$GIT_BRANCH_NAME" = "refs/heads/dev" ]; then \
    uv pip freeze | grep 'azul-.*==' | grep -v '^azul-restapi-server' | cut -d "=" -f 1 | xargs -I {} uv pip install --extra-index-url=$UV_INDEX_URL --system --upgrade --no-deps --prerelease allow '{}>=0.0.0-dev'; \
    else \
    uv pip freeze | grep 'azul-.*==' | grep -v '^azul-restapi-server' | cut -d "=" -f 1 | xargs -I {} uv pip install --extra-index-url=$UV_INDEX_URL --system --upgrade --no-deps '{}>=0.0.0'; \
    fi

FROM builder AS build-test
ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_DISABLE_PIP_VERSION_CHECK=yes
ARG PIP_CERT
ARG PIP_CLIENT_CERT
ARG PIP_TRUSTED_HOST
ARG PIP_INDEX_URL
ARG PIP_EXTRA_INDEX_URL
ARG GIT_BRANCH_NAME
# expected to be public registry (e.g pypi.org)
ARG UV_DEFAULT_INDEX
# expected to be private registry
ARG UV_INDEX_URL
ARG UV_INSECURE_HOST
# Ensure uv installs to the correct directory
ENV UV_PROJECT_ENVIRONMENT=/usr/local

RUN uv sync --frozen --no-editable --group plugins --group dev
# Upgrade to dev azul dependencies or upgrade non-dev azul dependencies depending on branch.
RUN if [ "$GIT_BRANCH_NAME" = "refs/heads/dev" ]; then \
    uv pip freeze | grep 'azul-.*==' | grep -v '^azul-restapi-server' | cut -d "=" -f 1 | xargs -I {} uv pip install --extra-index-url=$UV_INDEX_URL --system --upgrade --no-deps --prerelease allow '{}>=0.0.0-dev'; \
    else \
    uv pip freeze | grep 'azul-.*==' | grep -v '^azul-restapi-server' | cut -d "=" -f 1 | xargs -I {} uv pip install --extra-index-url=$UV_INDEX_URL --system --upgrade --no-deps '{}>=0.0.0'; \
    fi

FROM dhi.io/python:3.12-debian AS base
ENV DEBIAN_FRONTEND=noninteractive
ENV APP_MODULE=azul_restapi_server.main:app
ENV WORKER_CLASS=uvicorn.workers.UvicornWorker
ENV HOST=127.0.0.1
ENV PORT=8000
ENV PROMETHEUS_MULTIPROC_DIR=/tmp/
USER root
WORKDIR /logs 
COPY --from=builder /usr/local /usr/local

# run tests during build to verify dockerfile has all requirements
FROM dhi.io/python:3.12-debian-dev AS tester
ENV DEBIAN_FRONTEND=noninteractive
ENV APP_MODULE=azul_restapi_server.main:app
ENV WORKER_CLASS=uvicorn.workers.UvicornWorker
ENV HOST=127.0.0.1
ENV PORT=8000
ENV PROMETHEUS_MULTIPROC_DIR=/tmp/
ARG UID=65532
ARG GID=65532
COPY --from=build-test /usr/local /usr/local
WORKDIR /logs
WORKDIR /tmp/tests
# test scripts will be installed to the local user bin dir. Add local bin path for the azul user.
ENV PATH="/home/nonroot/.local/bin:$PATH"
COPY ./tests /tmp/tests
RUN --mount=type=secret,uid=$UID,gid=$GID,id=testSecret \
    set -a && \
    . /run/secrets/testSecret && \
    set +a && \
    pytest -o cache_dir=/tmp/cache --tb=short /tmp/tests

# generate empty file to copy to `release` stage so this stage is not skipped due to optimisations.
RUN touch /tmp/testingpassed

FROM base AS release
# copy from `tester` stage to ensure testing is not skipped due to build optimisations.
COPY --from=tester /tmp/testingpassed /tmp/
ENTRYPOINT ["azul-restapi-server"]
EXPOSE $PORT