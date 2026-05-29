# Build an image that runs the amazon-sync-for-actual CLI.
#
# Build:
#   docker build -t amazon-sync-for-actual .
#
# Run (mount your config + the Amazon CSV/ZIP; nothing secret is baked in):
#   docker run --rm \
#     -v "$PWD/config.ini:/config/config.ini:ro" \
#     -v "$PWD/Retail.OrderHistory.1.csv:/data/orders.csv:ro" \
#     amazon-sync-for-actual -c /config/config.ini --csv /data/orders.csv --dry-run
FROM python:3.12-slim-bookworm

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

# Secrets and order data are mounted at runtime, never copied into the image.
ENTRYPOINT ["amazon-sync-for-actual"]
CMD ["--help"]
