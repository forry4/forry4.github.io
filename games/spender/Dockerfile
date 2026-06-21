### Builder: build wheels for faster, cacheable installs
FROM python:3.11-slim AS builder
WORKDIR /build

# Build deps (only needed to compile wheels; not carried into the runtime image)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc && rm -rf /var/lib/apt/lists/*

COPY games/spender/requirements.txt /build/requirements.txt
RUN pip wheel --wheel-dir=/build/wheels -r /build/requirements.txt

# Compile the Cython hot-path module (valuation3, pure-Python mode) into a typed C extension.
# Done here (the builder has gcc); only the resulting .so is carried into the slim runtime image.
# The SAME valuation3.py runs as plain Python where this .so is absent (single source of truth).
RUN pip install --no-cache-dir cython
COPY games/spender/ai/az/valuation3.py /build/cy/valuation3.py
RUN cythonize -i -3 /build/cy/valuation3.py

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

# Drop in the precompiled Cython hot-path module (shadows valuation3.py -> faster variant-S V-leaf).
COPY --from=builder /build/cy/valuation3*.so /app/games/spender/ai/az/
# Build GATE: the compiled module must be byte-identical to the source (exact-value tests) or the
# image fails to build -- a Cython miscompile can never reach production.
RUN python -m pytest games/spender/tests/test_h3_valuation.py games/spender/tests/test_vsearch.py -q

EXPOSE 8000
# Shell form so ${PORT} is expanded at runtime; fall back to 8000 locally.
CMD ["sh", "-c", "uvicorn games.spender.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
