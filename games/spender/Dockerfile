### Builder: build wheels for faster, cacheable installs
FROM python:3.14-slim AS builder
WORKDIR /build

# Build deps (only needed to compile wheels; not carried into the runtime image)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc && rm -rf /var/lib/apt/lists/*

COPY games/spender/requirements.txt /build/requirements.txt
RUN pip wheel --wheel-dir=/build/wheels -r /build/requirements.txt

# Compile the Cython hot-path module (valuation3, pure-Python mode) into a typed C extension.
# Done here (the builder has gcc); only the resulting .so is carried into the slim runtime image.
# The SAME valuation3.py runs as plain Python where this .so is absent (single source of truth).
# Cython is PINNED: the C-array fast paths rely on version-specific pure-mode codegen behavior
# (e.g. cython.int[5][90] -> C int[90][5] dim reversal), validated on 3.2.5; an unpinned bump could
# change codegen and (caught by the build GATE below) block the deploy. Bump deliberately + re-gate.
# setuptools is NOT optional: `cythonize -i` builds through distutils, which Python 3.12 removed
# from the stdlib; setuptools supplies it. The 3.11 image happened to ship setuptools, so this
# line was missing and harmless until the move to 3.14, where cythonize dies on the import.
RUN pip install --no-cache-dir cython==3.2.5 setuptools==80.9.0
COPY games/spender/ai/serving/valuation3.py /build/cy/valuation3.py
RUN cythonize -i -3 /build/cy/valuation3.py

### Runtime: slim image that installs from the prebuilt wheels
FROM python:3.14-slim
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
COPY --from=builder /build/cy/valuation3*.so /app/games/spender/ai/serving/

# PRECOMPILE BYTECODE, or every Render wake compiles it again. .dockerignore drops the
# host's *.pyc (right: they are another interpreter's), the official python image
# strips the stdlib's .pyc to save space, and a woken free instance starts from the
# image with nothing written back — so before this, every cold start compiled the
# stdlib it imports plus ~56,000 lines of our own code on a fractional CPU. Prod's
# /health measured that import at 12.1s on 2026-11-13 (core/build_info.py, "boot").
# Done AFTER the last COPY into /app so no later layer changes a source under its
# .pyc; the default timestamp check then matches at runtime. Strict: a file that
# does not compile fails the build here instead of an import at boot. The stdlib pass
# skips site-packages (pip compiled it at install) and any test dirs (CPython ships
# deliberately broken files there; the slim image removes them, but do not bet on it).
RUN python -m compileall -q -j 0 -x '/(site-packages|test|tests|idle_test)/' \
        "$(python -c 'import sysconfig; print(sysconfig.get_path("stdlib"))')" \
 && python -m compileall -q -j 0 /app
# Build GATE: the compiled module must be byte-identical to the source (exact-value tests) or the
# image fails to build -- a Cython miscompile can never reach production.
RUN python -m pytest games/spender/tests/test_h3_valuation.py games/spender/tests/test_vsearch.py -q

EXPOSE 8000
# Shell form so ${PORT} is expanded at runtime; fall back to 8000 locally.
CMD ["sh", "-c", "uvicorn games.spender.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
