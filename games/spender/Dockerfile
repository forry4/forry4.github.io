### Builder: build wheels for faster installs and smaller final image
FROM python:3.11-slim AS builder
WORKDIR /build

# Install build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc libpq-dev && rm -rf /var/lib/apt/lists/*

# Copy requirements and build wheels
COPY games/spender/requirements.txt /build/requirements.txt
RUN pip wheel --wheel-dir=/build/wheels -r /build/requirements.txt

### Runtime image
FROM python:3.11-slim
WORKDIR /app

# Install any minimal system libs needed at runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 ca-certificates && rm -rf /var/lib/apt/lists/*

# Copy wheelhouse and install from it (offline install)
COPY --from=builder /build/wheels /wheels
RUN pip install --no-index --find-links=/wheels -r /wheels/../requirements.txt || true

# Copy full repo so imports like `games.*` work
COPY . /app

# Fallback: ensure all requirements installed (helps if wheels missed anything)
RUN pip install --no-cache-dir -r /app/games/spender/requirements.txt

EXPOSE 8000
CMD ["sh", "-c", "uvicorn games.spender.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
FROM python:3.11-slim

# Lightweight image for running the FastAPI app
WORKDIR /app

# Install runtime dependencies (uncomment apt-get lines if you need system libs)
RUN apt-get update && apt-get install -y --no-install-recommends \
	build-essential \
	&& rm -rf /var/lib/apt/lists/* || true

# Copy requirements and install Python packages
# Copy the full repository into the image so top-level packages (like `games`) are preserved
COPY . /app

# Install python requirements from the games/spender directory inside the repo
RUN pip install --no-cache-dir -r /app/games/spender/requirements.txt

# Expose a default port (documentation only; Render will inject $PORT)
EXPOSE 8000

# Start the server. Use the PORT environment variable when provided by the platform.
# Use shell form so ${PORT} is expanded at runtime. Fallback to 8000 locally.
CMD ["sh", "-c", "uvicorn games.spender.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
