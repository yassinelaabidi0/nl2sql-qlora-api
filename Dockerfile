FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

ARG INSTALL_ML=false

WORKDIR /app

COPY requirements-api.txt requirements.txt ./
RUN if [ "$INSTALL_ML" = "true" ]; then \
        pip install --upgrade pip && pip install -r requirements.txt; \
    else \
        pip install --upgrade pip && pip install -r requirements-api.txt; \
    fi

RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

COPY app ./app
COPY training ./training
COPY eval ./eval

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
