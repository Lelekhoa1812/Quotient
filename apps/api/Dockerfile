# Motivation vs Logic
# Motivation: The API task serves MCP and runs the meeting loop. The image has
# to contain ffmpeg, the AWS CLI, the worker tree, and contracts, laid out the
# way the process resolves them on disk.
# Logic: Bookworm slim. Build with --platform linux/arm64 from the repo root
# (`docker build -f apps/api/Dockerfile .`). The process listens on 0.0.0.0
# because the load balancer is not on the loopback interface.

FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip" -o /tmp/awscliv2.zip \
    && unzip -q /tmp/awscliv2.zip -d /tmp \
    && /tmp/aws/install \
    && rm -rf /tmp/aws /tmp/awscliv2.zip

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY apps/api apps/api
COPY apps/worker apps/worker
COPY contracts contracts
RUN mkdir -p /tmp/quotient \
    && useradd --create-home --uid 10001 quotient \
    && chown -R quotient:quotient /app /tmp/quotient
USER quotient
ENV PYTHONUNBUFFERED=1 \
    QUOTIENT_TRANSCRIPT_CACHE_DIR=/tmp/quotient
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "quotient.app:create_app", "--factory", "--app-dir", "apps/api", "--host", "0.0.0.0", "--port", "8080"]
