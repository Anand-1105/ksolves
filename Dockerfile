# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /app

# Install build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies into a prefix so we can copy them cleanly
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.13-slim AS runtime

LABEL maintainer="ShopWave Engineering"
LABEL description="ShopWave Autonomous Support Resolution Agent"

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY agent/       ./agent/
COPY utils/       ./utils/
COPY data/        ./data/
COPY main.py      .
COPY conftest.py  .

# Create output directory for audit/trace logs
RUN mkdir -p /app/output

# Non-root user for security
RUN useradd --no-create-home --shell /bin/false appuser \
    && chown -R appuser:appuser /app
USER appuser

# Environment defaults (override at runtime via --env or .env file)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TOOL_FAILURE_RATE=0.05 \
    LOG_LEVEL=INFO

# Expose output files as a volume so audit_log.json and trace_log.jsonl
# are accessible from the host after the container exits
VOLUME ["/app/output"]

# Default command: run the agent
CMD ["python", "main.py"]
