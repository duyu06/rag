FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/app/.cache/huggingface

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y --auto-remove build-essential \
    && rm -rf /root/.cache /var/lib/apt/lists/*

RUN groupadd --gid 10001 yaoke \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin yaoke \
    && mkdir -p /app/data/documents /app/demo-data /app/.cache/huggingface \
    && chown -R yaoke:yaoke /app /home/yaoke

COPY --chown=yaoke:yaoke app ./app
COPY --chown=yaoke:yaoke eval_dataset.json ./eval_dataset.json
COPY --chown=yaoke:yaoke eval_retrieval.py ./eval_retrieval.py

USER 10001:10001

EXPOSE 8001
CMD ["uvicorn", "app.main_agent:app", "--host", "0.0.0.0", "--port", "8001"]
