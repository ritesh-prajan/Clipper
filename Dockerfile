FROM python:3.11-slim

# Install FFmpeg, curl, and network dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and pre-built frontend static assets
COPY clipper ./clipper
COPY config.example.yaml ./config.example.yaml

# Create output volume mount point
RUN mkdir -p /app/live_output

EXPOSE 8080

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "clipper.web", "--host", "0.0.0.0", "--port", "8080", "--output-dir", "/app/live_output"]
