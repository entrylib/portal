FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# git: the app keeps a clone of the registry. The claimset package comes from PyPI, and is updated from it when the
# container starts.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 portal

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install .
# The scoring rubric (design §7.6), from PyPI; the image builds without it (the pages then show "–" for scores), and
# deploy/start.sh updates it at each start.
RUN pip install "entrylib-rubric>=0.4" \
 || echo "portal: the rubric could not be installed; scores will show –"

# Named volumes take their owner from these folders when first created, so the app (not root) can write to them.
RUN mkdir -p /srv/published /srv/registry /srv/submissions /home/portal/.local \
 && chown portal /srv/published /srv/registry /srv/submissions /home/portal/.local

USER portal
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status == 200 else 1)"
COPY deploy/start.sh /usr/local/bin/portal-start
# The newest claimset is installed into the portal user's site-packages (a volume) at each start, ahead of the one
# in the image; if that fails (no network), the last one installed is used. Updating claimset: restart the app.
CMD ["portal-start"]
