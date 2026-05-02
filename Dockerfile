# ------------------------------------------------------------------------------
# This Dockerfile defines the backup worker image for Compose-based deployments.
#
# The image uses a multi-stage build to separate dependency installation and
# binary fetch steps from the final runtime stage. Runtime data is externalised
# via mounted volumes for configuration, backup output, and logs.
# ------------------------------------------------------------------------------

# ------------------------------------------------------------------------------
# Pin Alpine image tag and digest for reproducible builds.
# ------------------------------------------------------------------------------
ARG ALP_VER
ARG ALPINE_IMAGE=alpine:${ALP_VER}

FROM ${ALPINE_IMAGE} AS python-deps

# ------------------------------------------------------------------------------
# Install Python tooling to build an isolated virtual environment.
#
# 1. "python3" provides the interpreter used by the worker.
# 2. "py3-pip" provides package installation for requirements.
# 3. "ca-certificates" enables trusted TLS for package downloads.
# ------------------------------------------------------------------------------
RUN apk add --no-cache \
    python3 \
    py3-pip \
    ca-certificates

# ------------------------------------------------------------------------------
# Build Python dependencies in "/opt/venv" for transfer into the runtime stage.
# ------------------------------------------------------------------------------
WORKDIR /build
COPY requirements.txt /build/requirements.txt
RUN python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir -r /build/requirements.txt

# ------------------------------------------------------------------------------
# Build the final runtime image with only required runtime dependencies.
# ------------------------------------------------------------------------------
FROM ${ALPINE_IMAGE}

# ------------------------------------------------------------------------------
# Add OCI metadata labels for image provenance and tooling integrations.
# ------------------------------------------------------------------------------
LABEL org.opencontainers.image.title="iCloud Drive Backup Container" \
      org.opencontainers.image.description="Incremental iCloud Drive backups with Telegram control." \
      org.opencontainers.image.source="https://github.com/papalozarou/pyiclodoc-drive" \
      org.opencontainers.image.licenses="GPL-3.0-only"

# ------------------------------------------------------------------------------
# Configure Python runtime defaults for container-friendly behaviour.
#
# 1. Disable bytecode file writes to keep writable layers clean.
# 2. Enable unbuffered stdout and stderr for immediate log visibility.
# 3. Prefer binaries from the transferred virtual environment.
# ------------------------------------------------------------------------------
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}"

# ------------------------------------------------------------------------------
# Install runtime packages only.
#
# 1. "python3" provides the interpreter used by installed dependencies.
# 2. "ca-certificates" supports secure outbound HTTPS requests.
# 3. "tzdata" ensures timezone-aware behaviour when required.
# 4. "su-exec" drops privileges after secrets are resolved as root.
# ------------------------------------------------------------------------------
RUN apk add --no-cache \
    python3 \
    ca-certificates \
    tzdata \
    su-exec

# ------------------------------------------------------------------------------
# Set the application working directory for all following instructions.
# ------------------------------------------------------------------------------
WORKDIR /app

# ------------------------------------------------------------------------------
# Copy runtime assets from the dependency build stage.
# ------------------------------------------------------------------------------
COPY --from=python-deps /opt/venv /opt/venv

# ------------------------------------------------------------------------------
# Copy worker application source code and operational scripts into the image.
# ------------------------------------------------------------------------------
COPY app /app/app
COPY scripts/entrypoint.sh scripts/start.sh scripts/healthcheck.sh /app/scripts/

# ------------------------------------------------------------------------------
# Mark startup scripts as executable so entrypoint and launcher can run.
# ------------------------------------------------------------------------------
RUN chmod +x \
    /app/scripts/entrypoint.sh \
    /app/scripts/start.sh \
    /app/scripts/healthcheck.sh

# ------------------------------------------------------------------------------
# Declare persistent mount points used by Compose volume bindings.
#
# 1. "/config" stores authentication and state files.
# 2. "/output" stores backup outputs.
# 3. "/logs" stores heartbeat and runtime log artefacts.
# ------------------------------------------------------------------------------
VOLUME ["/config", "/output", "/logs"]

# ------------------------------------------------------------------------------
# Define container health check policy for worker heartbeat monitoring.
#
# 1. Run every minute.
# 2. Time out after ten seconds.
# 3. Allow thirty seconds start period.
# 4. Mark unhealthy after three consecutive failures.
# 5. Invoke the script through "sh" so health does not depend on direct script
#    execution semantics alone.
# ------------------------------------------------------------------------------
HEALTHCHECK --interval=1m --timeout=10s --start-period=30s --retries=3 \
  CMD ["sh", "/app/scripts/healthcheck.sh"]

# ------------------------------------------------------------------------------
# Start the worker entrypoint script.
#
# N.B.
# Compose "init: true" is expected to provide PID 1 init behaviour.
# ------------------------------------------------------------------------------
ENTRYPOINT ["/app/scripts/entrypoint.sh"]
