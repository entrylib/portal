# The classifier service: OpenAlex's open topic model, CPU only. The model and OpenAlex's topic list are fetched
# at build, and the build fails if a model label matches no OpenAlex topic. Build with the secret
# openalex_api_key (an OpenAlex API key), e.g. docker build --secret id=openalex_api_key,env=OPENALEX_API_KEY .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 CLASSIFIER_DIR=/opt/classifier \
    HF_HUB_DISABLE_TELEMETRY=1

RUN useradd --create-home --uid 10002 classifier
WORKDIR /srv
COPY requirements.txt ./
# PyTorch from its CPU-only index first: from PyPI it is the CUDA build, which brings several GB of GPU libraries this
# CPU-only service never uses. The requirements then find it installed.
RUN pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.4" \
 && pip install -r requirements.txt
COPY labels.py download.py server.py ./
ARG CLASSIFIER_MODEL_REVISION=main
RUN --mount=type=secret,id=openalex_api_key \
    CLASSIFIER_MODEL_REVISION=${CLASSIFIER_MODEL_REVISION} python download.py \
 && chown -R classifier /opt/classifier

USER classifier
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8001/healthz').status == 200 else 1)"
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
