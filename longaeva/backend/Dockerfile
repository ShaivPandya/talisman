# python:3.12-slim — digest matches Talisman Dockerfile for reproducibility.
FROM python:3.12-slim@sha256:46cb7cc2877e60fbd5e21a9ae6115c30ace7a077b9f8772da879e4590c18c2e3

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/srv/longaeva/backend

WORKDIR /srv/longaeva/backend

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /srv/longaeva/data /srv/longaeva/docs /srv/longaeva/config /srv/longaeva/var/artifacts /tmp \
    && chown -R appuser:appuser /srv/longaeva /tmp

COPY requirements.txt requirements-dev.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements-dev.txt -c requirements.lock

COPY --chown=appuser:appuser . /srv/longaeva/backend
# data/ is copied by compose build context from the package root via a separate stage step;
# for image-only builds, create the expected layout so PACKAGE_ROOT resolves.
RUN mkdir -p /srv/longaeva/data /srv/longaeva/docs /srv/longaeva/config \
    && chown -R appuser:appuser /srv/longaeva

USER appuser

EXPOSE 8000

CMD ["uvicorn", "longaeva_app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
