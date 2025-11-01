import os
import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, Filter
from aiogram.types import Message
from ai_client import AIClient
from db import Database

load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация клиентов
ai_client = AIClient()
db = Database()

# Токены из .env
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")  # ID канала для постинга

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Временное хранилище сообщений из отслеживаемых чатов
chat_messages = {}


# Обработчик команды /start
@dp.message(Command("start"))
async def cmd_start(message: Message):
    welcome_text = """
🚀 Weekly-дайджест бот

Мониторинг чатов сообщества и создание еженедельных дайджестов.

📅 Расписание:
• Пн 10:00 - цели/блокеры недели
• Пт 19:00 - Weekly Digest

📋 Как добавить чат в мониторинг:
• Для публичных чатов/каналов - перешлите любое сообщение из чата
• Для приватных чатов - добавьте меня в чат и используйте /get_chat_id

Основные команды:
/get_chat_id - показать ID текущего чата
/add_chat <id_чата> - добавить чат для мониторинга
/remove_chat <id_чата> - удалить чат из мониторинга
/list_chats - список отслеживаемых чатов
/add_model <название> <модель> - добавить AI модель
/remove_model <название> - удалить AI модель
/models - список AI моделей
"""
    await message.answer(welcome_text)


# Обработчик команды /get_chat_id
@dp.message(Command("get_chat_id"))
async def cmd_get_chat_id(message: Message):
    """Показывает ID текущего чата"""
    try:
        chat_id = message.chat.id
        chat_type = message.chat.type

        # Определяем русское название типа чата
        chat_type_names = {
            "channel": "Канал",
            "group": "Группа",
            "supergroup": "Супергруппа",
            "private": "Личные сообщения"
        }
        chat_type_name = chat_type_names.get(chat_type, chat_type)
        chat_title = message.chat.title or "Без названия"

        response = f"""
📋 <b>Информация о текущем чате:</b>

<b>Тип:</b> {chat_type_name}
<b>ID:</b> <code>{chat_id}</code>
<b>Название:</b> {chat_title}

💡 <i>Чтобы добавить в мониторинг используйте:</i>
<code>/add_chat {chat_id}</code>
"""
        await message.answer(response, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Error getting chat ID: {e}")
        await message.answer("❌ Ошибка при получении ID чата")


# Обработчик для пересланных сообщений только из чатов/каналов
@dp.message(F.forward_from_chat)
async def handle_forwarded_message(message: Message):
    """Обрабатывает пересланные сообщения и показывает ID чата/канала"""
    try:
        if message.forward_from_chat:
            chat = message.forward_from_chat

            response = f"""
📋 Информация о пересланном чате/канале:

Тип: {chat.type}
ID: {chat.id}
Название: {chat.title or "Без названия"}

💡 Чтобы добавить в мониторинг используйте:
<code>/add_chat {chat.id}</code>
"""
            await message.answer(response, parse_mode="HTML")
        else:
            await message.answer("❌ Это не пересланное сообщение из чата/канала")

    except Exception as e:
        logger.error(f"Error processing forwarded message: {e}")
        await message.answer("❌ Ошибка при обработке пересланного сообщения")


# Обработчик команды /add_chat
@dp.message(Command("add_chat"))
async def cmd_add_chat(message: Message):
    try:
        args = message.text.split()[1:]
        if not args:
            await message.answer("❌ Использование: /add_chat <id_чата>\nПример: /add_chat -100123456789")
            return

        chat_id = args[0]

        if db.add_monitored_chat(chat_id):
            chat_messages[chat_id] = []
            await message.answer(f"✅ Чат с ID {chat_id} добавлен в мониторинг")
        else:
            await message.answer("❌ Ошибка при добавлении чата в мониторинг")
    except Exception as e:
        logger.error(f"Error adding chat: {e}")
        await message.answer("❌ Ошибка при добавлении чата в мониторинг")


# Обработчик команды /remove_chat
@dp.message(Command("remove_chat"))
async def cmd_remove_chat(message: Message):
    try:
        args = message.text.split()[1:]
        if not args:
            await message.answer("❌ Использование: /remove_chat <id_чата>\nПример: /remove_chat -100123456789")
            return

        chat_id = args[0]

        if db.remove_monitored_chat(chat_id):
            if chat_id in chat_messages:
                del chat_messages[chat_id]
            await message.answer(f"✅ Чат {chat_id} удален из мониторинга")
        else:
            await message.answer(f"❌ Чат {chat_id} не найден в списке мониторинга")
    except Exception as e:
        logger.error(f"Error removing chat: {e}")
        await message.answer("❌ Ошибка при удалении чата")


# Обработчик команды /list_chats
@dp.message(Command("list_chats"))
async def cmd_list_chats(message: Message):
    try:
        chats = db.get_monitored_chats()
        if not chats:
            await message.answer("📊 Нет отслеживаемых чатов")
            return

        chats_list = "\n".join([f"• ID {chat_id}" for chat_id in chats])
        await message.answer(f"📊 Отслеживаемые чаты:\n{chats_list}", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error listing chats: {e}")
        await message.answer("❌ Ошибка при получении списка чатов")


# Обработчик команды /add_model
@dp.message(Command("add_model"))
async def cmd_add_model(message: Message):
    try:
        args = message.text.split()[1:]
        if len(args) < 2:
            await message.answer(
                "❌ Использование: /add_model <название> <модель>\nПример: /add_model deepseek deepseek/deepseek-chat:free")
            return

        model_key = args[0]
        model_value = " ".join(args[1:])

        if ai_client.add_model(model_key, model_value):
            await message.answer(f"✅ AI модель '{model_key}' добавлена: {model_value}")
        else:
            await message.answer("❌ Ошибка при добавлении модели или модель уже существует")
    except Exception as e:
        logger.error(f"Error adding model: {e}")
        await message.answer("❌ Ошибка при добавлении AI модели")


# Обработчик команды /remove_model
@dp.message(Command("remove_model"))
async def cmd_remove_model(message: Message):
    try:
        args = message.text.split()[1:]
        if not args:
            await message.answer("❌ Использование: /remove_model <название>\nПример: /remove_model deepseek")
            return

        model_key = args[0]

        if ai_client.remove_model(model_key):
            await message.answer(f"✅ AI модель '{model_key}' удалена")
        else:
            await message.answer(f"❌ AI модель '{model_key}' не найдена")
    except Exception as e:
        logger.error(f"Error removing model: {e}")
        await message.answer("❌ Ошибка при удалении AI модели")


# Обработчик команды /models
@dp.message(Command("models"))
async def cmd_models(message: Message):
    try:
        models_text = ai_client.get_available_models()
        await message.answer(models_text)
    except Exception as e:
        logger.error(f"Error getting models: {e}")
        await message.answer("❌ Ошибка при получении списка AI моделей")


# Обработчик всех сообщений в отслеживаемых чатах
class MonitoredChatsFilter(Filter):
    def __init__(self, db):
        self.db = db

    async def __call__(self, message: Message) -> bool:
        # Всегда получаем свежий список из БД
        monitored_chats = self.db.get_monitored_chats()
        chat_ids = [chat_id for chat_id in monitored_chats]
        return message.chat.id in chat_ids


# Обработчик для групп и супергрупп
@dp.message(MonitoredChatsFilter(db))
async def handle_monitored_messages(message: Message):
    await process_chat_message(message)


# Обработчик для каналов
@dp.channel_post(MonitoredChatsFilter(db))
async def handle_monitored_channel_posts(message: Message):
    await process_chat_message(message)


async def process_chat_message(message: Message):
    try:
        chat_id = message.chat.id

        if chat_id not in chat_messages:
            chat_messages[chat_id] = []

        # Сохраняем текст сообщения
        if message.text and not message.text.startswith('/'):
            chat_messages[chat_id].append(message.text)

            # Ограничиваем количество сообщений в памяти
            if len(chat_messages[chat_id]) > 100:
                chat_messages[chat_id] = chat_messages[chat_id][-50:]

    except Exception as e:
        logger.error(f"Error handling monitored message: {e}")


# Функция для создания понедельничного поста (цели/блокеры)
async def create_monday_post():
    """Создает пост с целями/блокерами на неделю"""
    try:
        if not CHANNEL_ID:
            logger.error("CHANNEL_ID не установлен в .env")
            return

        all_messages = []
        for chat_id, messages in chat_messages.items():
            if messages:
                all_messages.extend(messages[-20:])

        if not all_messages:
            logger.info("Нет сообщений для анализа по понедельникам")
            return

        prompt = f"""
На основе сообщений из чатов сообщества за последние дни, предложи цели и возможные блокеры на текущую неделю.

Сообщения из чатов:
{"; ".join(all_messages)}

Формат ответа:
🎯 Цели недели:
1. [цель 1]
2. [цель 2]

🛑 Возможные блокеры:
• [блокер 1]
• [блокер 2]

💡 Рекомендации:
- [рекомендация]

Будь конкретным и ориентированным на действие.
"""

        # Автоматически переключается между моделями при ошибках
        analysis = ai_client.send_request(prompt)
        post_text = f"📅 **Понедельник: Цели и блокеры недели**\n\n{analysis}"

        await bot.send_message(chat_id=CHANNEL_ID, text=post_text, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error creating Monday post: {e}")
        # TODO? добавить отправку уведомления об ошибке
        # await bot.send_message(chat_id=ADMIN_ID, text=f"❌ Ошибка понедельничного поста: {e}")


# Функция для создания пятничного дайджеста
async def create_friday_digest():
    """Создает еженедельный дайджест"""
    try:
        if not CHANNEL_ID:
            logger.error("CHANNEL_ID не установлен в .env")
            return

        all_messages = []
        for chat_id, messages in chat_messages.items():
            if messages:
                all_messages.extend(messages)

        if not all_messages:
            logger.info("Нет сообщений для Friday Digest")
            return

        prompt = f"""
Создай еженедельный дайджест на основе сообщений из чатов сообщества.

Сообщения из чатов:
{"; ".join(all_messages)}

Структура дайджеста:
👥 Новые участники
💡 Идеи 
🔬 Лаб (next/stop)
🚀 Апдейты проектов
🆘 Помощь 
🛠️ Инструмент недели
✅ Решения

Будь кратким, информативным и используй эмодзи для наглядности.
"""

        # Автоматически переключается между моделями при ошибках
        analysis = ai_client.send_request(prompt)
        post_text = f"📊 **Weekly Digest**\n\n{analysis}"

        await bot.send_message(chat_id=CHANNEL_ID, text=post_text, parse_mode="Markdown")

        # Очищаем сообщения после публикации дайджеста
        for chat_id in chat_messages:
            chat_messages[chat_id] = []

    except Exception as e:
        logger.error(f"Error creating Friday digest: {e}")
        # TODO?
        # await bot.send_message(chat_id=ADMIN_ID, text=f"❌ Ошибка пятничного дайджеста: {e}")


# Задачи для расписания постинга
async def scheduled_posting():
    """Запускает периодическую проверку времени для постинга"""
    while True:
        try:
            now = datetime.now()
            current_time = now.strftime("%H:%M")
            weekday = now.strftime("%A")

            # Понедельник 10:00 - цели/блокеры
            if weekday == "Monday" and current_time == "10:00":
                await create_monday_post()
                await asyncio.sleep(60)

            # Пятница 19:00 - Weekly Digest
            elif weekday == "Friday" and current_time == "19:00":
                await create_friday_digest()
                await asyncio.sleep(60)

            await asyncio.sleep(30)  # Проверяем каждые 30 секунд
        except Exception as e:
            logger.error(f"Error in scheduled posting: {e}")
            await asyncio.sleep(60)


# Запуск бота
async def main():
    logger.info("🚀 Weekly-дайджест бот запускается...")

    # Загружаем отслеживаемые чаты в память
    chats = db.get_monitored_chats()
    for chat_id in chats:
        chat_messages[chat_id] = []

    stats = ai_client.get_stats()
    logger.info(f"AI моделей: {stats['ai_models']}")
    logger.info(f"Отслеживаемых чатов: {stats['monitored_chats']}")

    # Запускаем фоновую задачу постинга
    asyncio.create_task(scheduled_posting())

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
