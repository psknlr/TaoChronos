# The full corpus's server (cloud/README.md): taochronos over the store the site carries, its full-text index built and
# its caches warmed while the image is built.  Built by wrangler from the repository's root (image_build_context), after
# the workflow fetched the store cloud/store.json names into cloud/.store/<sha256>.sqlite.xz.
# The base image by digest (python:3.12-slim as published on 2026-10-26: Python 3.12.16; Dependabot proposes the next),
# and every Python package from the hashed lockfiles in requirements/ (requirements/README.md): the same bytes each build.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TAOCHRONOS_HOME=/srv/taochronos TAOCHRONOS_DATA=/srv/data
WORKDIR /srv/taochronos
COPY requirements/build.txt requirements/runtime.txt ./requirements/
RUN pip install --require-hashes -r requirements/build.txt -r requirements/runtime.txt
COPY pyproject.toml README.md ./
COPY src ./src
# built with the hashed setuptools above (no build isolation: nothing fetched unpinned), which then leaves the image
RUN pip install --no-deps --no-build-isolation . && pip uninstall --yes --quiet setuptools wheel packaging \
    && rm -rf build src/*.egg-info requirements
COPY architecture-policy.yaml ./
COPY profiles ./profiles
COPY domains ./domains
COPY corpus/catalog ./corpus/catalog
COPY corpus/demo ./corpus/demo
COPY corpus/modern ./corpus/modern
COPY agents ./agents
COPY skills ./skills
COPY evals/gold ./evals/gold

# unpack and check the store, index it with this code's normalizer, warm the tools' caches (python -m taochronos.chat.cloud)
FROM base AS store
COPY cloud/store.json /build/store.json
COPY cloud/.store/ /build/
RUN python -m taochronos.chat.cloud prepare --manifest /build/store.json /build /srv/data

# the server runs unprivileged: it writes its data (sessions, research jobs, the caches beside the store) and the YAML
# cache in its home, never the code or the packages, which stay root's
FROM base
RUN useradd --system --uid 10001 --user-group --create-home --home-dir /home/taochronos --shell /usr/sbin/nologin taochronos
COPY --from=store --chown=10001:10001 /srv/data /srv/data
USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "taochronos.chat.cloud", "serve"]
