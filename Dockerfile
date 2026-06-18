FROM python:3.11-alpine AS builder
RUN apk add --no-cache gcc musl-dev
WORKDIR /install
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt
FROM python:3.11-alpine
RUN apk add --no-cache ffmpeg
WORKDIR /app
COPY --from=builder /install /usr/local
COPY main.py .
RUN adduser -D botuser && chown -R botuser:botuser /app
USER botuser
CMD ["python", "main.py"]
