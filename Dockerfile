# Workforce Simulator — Dockerfile
#
# Build:   docker build -t workforce-simulator .
# Run:     docker-compose up   (preferred — handles volumes and env)
#
# The image installs all pinned dependencies from requirements.txt then copies
# the application source. State and credentials are mounted as volumes at
# runtime so they persist across container restarts without being baked in.
#
# Cloud deployment (Railway / Render):
#   - Set DEPLOYMENT_KEY and CREDENTIALS_YAML_B64 as environment variables.
#   - Mount a persistent volume at /app/state to retain simulation state.
#   - See render.yaml / railway.toml for platform-specific configuration.

FROM python:3.11-slim

# Metadata
LABEL description="Call Centre Workforce Simulator"
LABEL maintainer="Alex Pappas"

# Keep Python output unbuffered so logs appear immediately
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install curl for the HEALTHCHECK (and any future OS-level tooling).
# Done before pip install so this layer is cached independently.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (layer-cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Create writable directories that are mounted as volumes at runtime.
# These directories must exist in the image so the app can write to them
# even if no volume is mounted (e.g. during a plain docker run).
RUN mkdir -p state configs

# Streamlit listens on 8501 by default
EXPOSE 8501

# Healthcheck — verifies the app is responding
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD curl -f http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["streamlit", "run", "app.py", \
            "--server.port=8501", \
            "--server.address=0.0.0.0", \
            "--server.headless=true", \
            "--browser.gatherUsageStats=false"]
