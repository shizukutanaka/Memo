# Enterprise Secure Memo System - Production Dockerfile
# ====================================================
# Multi-stage build optimized for security and performance

# Build stage
FROM python:3.11-slim as builder

LABEL maintainer="Enterprise Memo System Team"
LABEL version="2.0.0"
LABEL description="Military-Grade Secure Memo Management System"

# Install system dependencies for building
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libssl-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment with security hardening
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Set build arguments
ARG REQUIREMENTS_FILE=requirements-production.txt
ARG BUILD_DATE
ARG VCS_REF

# Copy and install Python dependencies
COPY ${REQUIREMENTS_FILE} .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir --compile --no-deps -r ${REQUIREMENTS_FILE} && \
    pip cache purge

# Runtime stage
FROM python:3.11-slim

# Add metadata labels
LABEL org.opencontainers.image.title="Secure Memo System" \
      org.opencontainers.image.description="Military-Grade Secure Memo Management System" \
      org.opencontainers.image.version="2.0.0" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.vendor="Enterprise Solutions" \
      org.opencontainers.image.licenses="MIT"

# Create non-root user with specific UID/GID for consistency
RUN groupadd -r -g 1000 memo && \
    useradd --no-log-init -r -u 1000 -g memo -d /app -s /bin/bash memo

# Install runtime system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    curl \
    ca-certificates \
    tzdata \
    && echo 'debconf debconf/frontend select Noninteractive' | debconf-set-selections \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean -y \
    && apt-get autoclean -y \
    && rm -rf /var/cache/apt/*

# Copy virtual environment from builder stage
COPY --from=builder --chown=memo:memo /opt/venv /opt/venv

# Set environment variables
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MEMO_ENV=production \
    MEMO_LOG_LEVEL=INFO \
    SQLITE_TMPDIR=/tmp \
    HOME=/app

# Create application directories with proper permissions
RUN mkdir -p /app/data /app/logs /app/backups /app/temp /app/config && \
    chown -R memo:memo /app

# Copy application files with proper ownership
COPY --chown=memo:memo memo_system.py /app/
COPY --chown=memo:memo config.py /app/
COPY --chown=memo:memo i18n.py /app/
COPY --chown=memo:memo monitoring_alerting.py /app/
COPY --chown=memo:memo backup_ultimate.py /app/
COPY --chown=memo:memo requirements.txt /app/
COPY --chown=memo:memo requirements-production.txt /app/

# Copy additional runtime files
COPY --chown=memo:memo README.md /app/
COPY --chown=memo:memo README_en.md /app/
COPY --chown=memo:memo README_ja.md /app/

# Set working directory
WORKDIR /app

# Switch to non-root user
USER memo

# Health check - simplified for Docker compatibility
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python3 -c "import sqlite3, os; conn = sqlite3.connect(os.environ.get('MEMO_DB_PATH', '/app/data/memos.db')); conn.execute('SELECT 1'); conn.close(); print('OK')"

# Security: Run as non-root
USER memo

# Set resource limits (can be overridden in docker-compose)
ENV MEMO_MAX_MEMORY=1G \
    MEMO_MAX_CPU=2

# Expose port for web interface
EXPOSE 8080

# Volume mounts for data persistence
VOLUME ["/app/data", "/app/logs", "/app/backups"]

# Default command - start the memo system
CMD ["python3", "memo_system.py", "--help"]