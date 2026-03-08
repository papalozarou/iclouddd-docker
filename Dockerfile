# ------------------------------------------------------------------------------
# This Dockerfile defines the backup worker image for Compose-based deployments.
#
# The image uses Alpine Linux, installs Python runtime dependencies, and copies
# worker code and helper scripts into "/app". Runtime data is externalised via
# mounted volumes for configuration, backup output, and logs.
# ------------------------------------------------------------------------------
FROM alpine:3.20

# ------------------------------------------------------------------------------
# Configure Python runtime defaults for container-friendly behaviour.
#
# 1. Disable bytecode file writes to keep writable layers clean.
# 2. Enable unbuffered stdout and stderr for immediate log visibility.
# ------------------------------------------------------------------------------
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# ------------------------------------------------------------------------------
# Install required OS packages for runtime dependencies and health checks.
#
# 1. "python3" and "py3-pip" provide the Python runtime and package installer.
# 2. "su-exec" supports user switching in entrypoint workflows.
# 3. "ca-certificates" and "curl" support secure outbound HTTPS requests.
# 4. "tzdata" ensures timezone-aware behaviour when required.
# 5. "jq" supports JSON parsing in shell-based operations.
# ------------------------------------------------------------------------------
RUN apk add --no-cache \
    python3 \
    py3-pip \
    su-exec \
    ca-certificates \
    curl \
    tzdata \
    jq

# ------------------------------------------------------------------------------
# Download "microcheck" for supported architectures when available.
#
# 1. Detect Alpine architecture and map to release artifact naming.
# 2. Attempt download and chmod without failing the image build if missing.
#
# N.B.
# Health checks remain functional without "microcheck"; this binary is optional.
# ------------------------------------------------------------------------------
RUN set -eux; \
    arch="$(apk --print-arch)"; \
    target=""; \
    [ "$arch" = "x86_64" ] && target="amd64" || true; \
    [ "$arch" = "aarch64" ] && target="arm64" || true; \
    if [ -n "$target" ]; then \
      curl -fsSL "https://github.com/tarampampam/microcheck/releases/latest/download/microcheck-linux-${target}" -o /usr/local/bin/microcheck || true; \
      chmod +x /usr/local/bin/microcheck || true; \
    fi

# ------------------------------------------------------------------------------
# Set the application working directory for all following instructions.
# ------------------------------------------------------------------------------
WORKDIR /app

# ------------------------------------------------------------------------------
# Copy and install Python dependencies first to improve build layer reuse.
# ------------------------------------------------------------------------------
COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir -r /app/requirements.txt

# ------------------------------------------------------------------------------
# Copy worker application source code and operational scripts into the image.
# ------------------------------------------------------------------------------
COPY app /app/app
COPY scripts /app/scripts

# ------------------------------------------------------------------------------
# Mark startup scripts as executable so entrypoint and launcher can run.
# ------------------------------------------------------------------------------
RUN chmod +x /app/scripts/entrypoint.sh /app/scripts/start.sh

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
# ------------------------------------------------------------------------------
HEALTHCHECK --interval=1m --timeout=10s --start-period=30s --retries=3 \
  CMD /app/scripts/healthcheck.sh

# ------------------------------------------------------------------------------
# Start the worker entrypoint script.
#
# N.B.
# Compose "init: true" is expected to provide PID 1 init behaviour.
# ------------------------------------------------------------------------------
ENTRYPOINT ["/app/scripts/entrypoint.sh"]
