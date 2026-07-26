FROM python:3.12-slim-bookworm AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip wheel --wheel-dir /wheels .

FROM python:3.12-slim-bookworm

ARG HADA_UID=10001
ARG HADA_GID=10001
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/hada/.venv/bin:/usr/local/bin:/usr/bin:/bin

RUN apt-get update \
    && apt-get install -y --no-install-recommends bubblewrap ca-certificates git tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "${HADA_GID}" hada \
    && useradd --uid "${HADA_UID}" --gid "${HADA_GID}" --home-dir /var/lib/hada --create-home --shell /usr/sbin/nologin hada

RUN python -m venv /opt/hada/.venv
COPY --from=build /wheels /wheels
RUN /opt/hada/.venv/bin/pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels

WORKDIR /opt/hada
COPY --chown=root:hada config ./config
COPY --chown=root:hada src/hada/db/migrations ./src/hada/db/migrations
COPY --chown=root:hada deploy ./deploy
COPY --chown=root:hada scripts/container-entrypoint.sh ./scripts/container-entrypoint.sh
RUN chmod 0755 ./scripts/container-entrypoint.sh \
    && install -d -o hada -g hada -m 0750 /var/lib/hada /var/log/hada

USER hada
EXPOSE 9108
ENTRYPOINT ["/usr/bin/tini", "--", "/opt/hada/scripts/container-entrypoint.sh"]
CMD ["hada", "orchestrator", "run", "--config", "/opt/hada/config/hada.yaml"]
