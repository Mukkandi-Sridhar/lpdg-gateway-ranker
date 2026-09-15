FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code only. The data is mounted at /app/data at run time, never copied into the image.
COPY pyproject.toml baseline_3sigma.py validate_submission.py ./
COPY gateway_ranker ./gateway_ranker
COPY api ./api
COPY scripts ./scripts

ENV DATA_DIR=/app/data \
    PREDICTIONS_PATH=/app/output/predictions.csv \
    RESULTS_PATH=/app/output/results.json

EXPOSE 8000

# Build the rankings, check the file with LPDG's validator, then serve the API.
# If the first run fails, the API still starts so GET /health can say why.
CMD ["sh", "-c", "python -m gateway_ranker.cli predict && python validate_submission.py \"$PREDICTIONS_PATH\" || echo 'initial run failed: see the error above and GET /health'; exec uvicorn api.main:create_app --factory --host 0.0.0.0 --port 8000 --no-access-log"]
