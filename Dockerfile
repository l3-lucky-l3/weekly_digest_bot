FROM python:3.11-slim

WORKDIR /app

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Копируем requirements первыми для кэширования
COPY requirements.txt .

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем исходники
COPY src/ ./src/

# Создаем директорию для данных
RUN mkdir -p /app/data

# Запускаем бота
CMD ["python", "-m", "src.main"]