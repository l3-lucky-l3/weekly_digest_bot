# Создаем .env файл с настройками
cp .env.example .env
# Редактируем .env - добавляем BOT_TOKEN, OPENROUTER_API_KEY, CHANNEL_ID

# Запускаем
docker-compose up -d

# Просмотр логов
docker-compose logs -f

# Остановка
docker-compose down