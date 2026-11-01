# Build context is the REPO ROOT (see docker-compose.yml) so ml/ can be copied in.
FROM python:3.12-slim
# lightgbm needs the OpenMP runtime
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY ml ./ml
ENV PYTHONPATH=/srv
EXPOSE 8000
CMD ["sh", "-c", "python -m app.init_db && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
