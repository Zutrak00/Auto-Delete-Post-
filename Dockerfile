FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY autodelete ./autodelete

# Accounts, tokens and history live here; mount a volume so they survive upgrades.
ENV AUTODELETE_DB=/app/data/autodelete.db
VOLUME /app/data
EXPOSE 8080

# Listening on 0.0.0.0 inside the container requires AUTODELETE_PASSWORD to be set.
CMD ["python", "-m", "autodelete", "web", "--host", "0.0.0.0", "--port", "8080"]
