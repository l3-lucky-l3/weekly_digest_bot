## Создаем .env файл с настройками
```bash
cp .env.example .env
# Редактируем .env - добавляем BOT_TOKEN, OPENROUTER_API_KEY, CHANNEL_ID
```

## Запуск
```bash
docker-compose up -d
```

## Просмотр логов
```bash
docker-compose logs -f
```

## Остановка
```bash
docker-compose down
```