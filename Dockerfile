FROM python:3.12-slim AS builder

ARG EMBED_MODEL=intfloat/multilingual-e5-base
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/opt/hf \
    EMBED_MODEL=${EMBED_MODEL} \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /build
RUN python -m venv /opt/venv
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
COPY App/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt
RUN python -c "import os; from sentence_transformers import SentenceTransformer; SentenceTransformer(os.environ['EMBED_MODEL'])"

FROM python:3.12-slim AS runtime

ARG EMBED_MODEL=intfloat/multilingual-e5-base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/hf \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    EMBED_MODEL=${EMBED_MODEL} \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/hf /opt/hf
COPY App/main.py App/embedding.py App/qa.py App/settings.py App/text_search.py ./App/
COPY App/static/ ./App/static/
COPY data/index/*.txt ./data/index/

USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)" || exit 1
CMD ["uvicorn", "App.main:app", "--host", "0.0.0.0", "--port", "8000"]
