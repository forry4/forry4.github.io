### Builder: build wheels for faster, cacheable installs
FROM python:3.11-slim AS builder
WORKDIR /build

# Build deps (only needed to compile wheels; not carried into the runtime image)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc && rm -rf /var/lib/apt/lists/*

COPY games/spender/requirements.txt /build/requirements.txt
RUN pip wheel --wheel-dir=/build/wheels -r /build/requirements.txt

### Runtime: slim image that installs from the prebuilt wheels
FROM python:3.11-slim
WORKDIR /app

# CA roots for outbound TLS (the libSQL/Turso connection)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates && rm -rf /var/lib/apt/lists/*

# Install Python deps from the wheelhouse (offline, no compiler needed at runtime)
COPY --from=builder /build/wheels /wheels
COPY games/spender/requirements.txt /app/games/spender/requirements.txt
RUN pip install --no-index --find-links=/wheels -r /app/games/spender/requirements.txt

# Copy the full repo so top-level packages (games, books, shared) resolve
COPY . /app

EXPOSE 8000
# Shell form so ${PORT} is expanded at runtime; fall back to 8000 locally.
CMD ["sh", "-c", "uvicorn games.spender.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
