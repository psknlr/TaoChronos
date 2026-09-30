# The full corpus's server (cloud/README.md): taochronos over the store the site carries, its full-text index built and
# its caches warmed while the image is built.  Built by wrangler from the repository's root (image_build_context), after
# the workflow fetched the store cloud/store.json names into cloud/.store/<sha256>.sqlite.xz.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TAOCHRONOS_HOME=/srv/taochronos TAOCHRONOS_DATA=/srv/data
WORKDIR /srv/taochronos
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install . && rm -rf build src/*.egg-info
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

FROM base
COPY --from=store /srv/data /srv/data
EXPOSE 8080
CMD ["python", "-m", "taochronos.chat.cloud", "serve"]
