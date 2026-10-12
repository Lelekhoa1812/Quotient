# Motivation vs Logic
# Motivation: The worker repository and the chart sandbox share one image.
# The service stays at zero tasks until the queue has depth, and the sandbox
# task is started only by RunTask.
# Logic: Same runtime as the API image. The default command stays up without
# reading SQS. Build with --platform linux/arm64 from the repo root
# (`docker build -f apps/worker/Dockerfile .`).

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
CMD ["python", "apps/worker/idle.py"]
