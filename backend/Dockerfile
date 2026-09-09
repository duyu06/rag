FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/app/.cache/huggingface

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY eval_dataset.json ./eval_dataset.json
COPY eval_retrieval.py ./eval_retrieval.py
RUN mkdir -p /app/data/documents /app/demo-data

EXPOSE 8001
CMD ["uvicorn", "app.main_agent:app", "--host", "0.0.0.0", "--port", "8001"]
