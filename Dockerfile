# --- Этап 1: Сборка (Builder) ---
FROM python:3.11-alpine AS builder

RUN apk add --no-cache gcc musl-dev

WORKDIR /install
COPY requirements.txt .

# Установка зависимостей в папку /install
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- Этап 2: Финальный образ ---
FROM python:3.11-alpine

# Устанавливаем только ffmpeg (если он нужен)
RUN apk add --no-cache ffmpeg

WORKDIR /app

# Копируем установленные зависимости из этапа builder
COPY --from=builder /install /usr/local

# Копируем код приложения
COPY main.py .

# Запускаем от непривилегированного пользователя для безопасности
RUN adduser -D botuser
USER botuser

CMD ["python", "main.py"]
