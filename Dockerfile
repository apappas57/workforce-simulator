# Workforce Simulator — Dockerfile
#
# Build:   docker build -t workforce-simulator .
# Run:     docker-compose up   (preferred — handles volumes and env)
#
# The image installs all pinned dependencies from requirements.txt then copies
# the application source. State and credentials are mounted as volumes at
# runtime so they persist across container restarts without being baked in.

FROM python:3.11-slim

# Metadata
LABEL description="Call Centre Workforce Simulator"
LABEL maintainer="Alex Pappas"

# Keep Python output unbuffered so logs appear immediately
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (layer-cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Create the state directory so the persistence layer has a writable home.
# docker-compose mounts ./state here so data survives container rebuilds.
RUN mkdir -p state

# Streamlit listens on 8501 by default
EXPOSE 8501

# Healthcheck — verifies the app is responding
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["streamlit", "run", "app.py", \
            "--server.port=8501", \
            "--server.address=0.0.0.0", \
            "--server.headless=true", \
            "--browser.gatherUsageStats=false"]
