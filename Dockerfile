FROM python:3.11-slim

WORKDIR /app

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Копируем requirements первыми для кэширования
COPY requirements.txt .

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем ВСЕ файлы проекта
COPY . .

# Создаем volume для базы данных
VOLUME /app/data

# Создаем директорию для данных
RUN mkdir -p /app/data

# Запускаем бота
CMD ["python", "src/main.py"]