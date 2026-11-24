FROM python:3.12-slim AS builder

ARG EMBED_MODEL=intfloat/multilingual-e5-large
ARG EMBED_MODEL_REVISION=main
ARG RERANK_MODEL=BAAI/bge-reranker-v2-m3
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/opt/hf \
    EMBED_MODEL=${EMBED_MODEL} \
    EMBED_MODEL_REVISION=${EMBED_MODEL_REVISION} \
    RERANK_MODEL=${RERANK_MODEL} \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /build
RUN python -m venv /opt/venv
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
COPY App/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt
RUN python -c "import os; from sentence_transformers import SentenceTransformer, CrossEncoder; SentenceTransformer(os.environ['EMBED_MODEL'], revision=os.environ['EMBED_MODEL_REVISION']); CrossEncoder(os.environ['RERANK_MODEL'])"

FROM python:3.12-slim AS runtime

ARG EMBED_MODEL=intfloat/multilingual-e5-large
ARG EMBED_MODEL_REVISION=main
ARG RERANK_MODEL=BAAI/bge-reranker-v2-m3
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/hf \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    EMBED_MODEL=${EMBED_MODEL} \
    EMBED_MODEL_REVISION=${EMBED_MODEL_REVISION} \
    RERANK_MODEL=${RERANK_MODEL} \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/hf /opt/hf
COPY App/main.py App/embedding.py App/system.py App/settings.py App/text_search.py App/document_processing.py App/observability.py App/topic_modules.py App/intent.py App/bot_templates.py App/azerbaijani.py App/insurance_terminology.py App/vector_store.py App/query_resolution.py App/rerank.py ./App/
COPY App/config/ ./App/config/
COPY App/query_plan.py App/evaluation_capture.py ./App/
COPY App/legal_documents.py App/legal_evidence.py App/legal_answers.py App/answer_recovery.py App/source_authority.py App/gemini_generation.py ./App/
COPY App/verified_release.py ./App/
COPY App/prepare_index.py ./App/
COPY evaluation/verify_legal_scope.py evaluation/verify_legal_scope_v2.py evaluation/legal_verifier_hardening_policy_v2.json evaluation/gold_framework.py evaluation/build_real_insurance_dataset.py evaluation/evaluate_latest_seven.py evaluation/rag_run.py ./evaluation/
COPY App/static/ ./App/static/
COPY data/index/ ./data/index/
COPY data/legal_source_versions.json ./data/
COPY data/staged_legal/ ./data/staged_legal/

COPY App/accounts.py ./App/
RUN install -d -m 0700 -o appuser -g appuser /app/var/accounts

USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)" || exit 1
CMD ["uvicorn", "App.main:app", "--host", "0.0.0.0", "--port", "8000"]
