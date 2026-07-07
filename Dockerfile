ARG REGISTRY="dhi.io"
ARG BUILD_IMAGE='python'
ARG BUILD_TAG='3.12-debian-dev'
ARG BASE_IMAGE='python'
ARG BASE_TAG='3.12-debian'

FROM $REGISTRY/$BUILD_IMAGE:$BUILD_TAG AS builder
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
    uv pip list --format=freeze | grep 'azul-.*==' | grep -v '^azul-restapi-server' | cut -d "=" -f 1 | xargs -I {} uv pip install --extra-index-url=$UV_INDEX_URL --system --upgrade --no-deps --prerelease allow '{}>=0.0.0-dev'; \
    else \
    uv pip list --format=freeze | grep 'azul-.*==' | grep -v '^azul-restapi-server' | cut -d "=" -f 1 | xargs -I {} uv pip install --extra-index-url=$UV_INDEX_URL --system --upgrade --no-deps '{}>=0.0.0'; \
    fi

FROM builder AS builder-test
RUN uv sync --frozen --no-editable --group plugins --group dev

FROM $REGISTRY/$BASE_IMAGE:$BASE_TAG AS base
ENV APP_MODULE=azul_restapi_server.main:app
ENV WORKER_CLASS=uvicorn.workers.UvicornWorker
ENV HOST=127.0.0.1
ENV PORT=8000
ENV PROMETHEUS_MULTIPROC_DIR=/tmp/
WORKDIR /logs
COPY --from=builder /usr/local /usr/local

# run tests during build to verify dockerfile has all requirements
FROM $REGISTRY/$BUILD_IMAGE:$BUILD_TAG AS tester
ENV APP_MODULE=azul_restapi_server.main:app
ENV WORKER_CLASS=uvicorn.workers.UvicornWorker
ENV HOST=127.0.0.1
ENV PORT=8000
ENV PROMETHEUS_MULTIPROC_DIR=/tmp/
# Have to hardcode anyway to get past buildah version 1.39 (version 1.45 will allow variable expansion in --mount)
# ARG UID=65532
# ARG GID=65532
USER nonroot
WORKDIR /logs
COPY --from=builder-test /usr/local /usr/local
COPY ./tests /tmp/tests
RUN --mount=type=secret,id=testSecret,uid=65532,gid=65532 \
    set -a && . /run/secrets/testSecret && set +a && \
    pytest -o cache_dir=/tmp/cache --tb=short /tmp/tests

# generate empty file to copy to `release` stage so this stage is not skipped due to optimisations.
RUN touch /tmp/testingpassed

FROM base AS release
# copy from `tester` stage to ensure testing is not skipped due to build optimisations.
COPY --from=tester /tmp/testingpassed /tmp/
# Set working directory to bin directory to make command execution easier.
WORKDIR /usr/local/bin
ENTRYPOINT ["azul-restapi-server"]
EXPOSE $PORT
