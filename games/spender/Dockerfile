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
