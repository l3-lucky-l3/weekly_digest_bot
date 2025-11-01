import os
import asyncio
import logging
from datetime import datetime, time
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
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
🤖 Бот мониторинга чатов и AI-анализа

Я отслеживаю сообщения в чатах, анализирую их с помощью AI и публикую сводки в канал.

Основные команды:
/get_chat_id - показать ID текущего чата
/monitor_chat - добавить текущий чат для мониторинга
/stop_monitor - остановить мониторинг чата
/list_chats - список отслеживаемых чатов
/set_schedule <время> - установить время постинга (например: /set_schedule 18:00)
/add_model <название> <модель> - добавить AI модель
/models - список AI моделей

💡 Просто перешлите любое сообщение из чата, и я покажу его ID!
"""
    await message.answer(welcome_text)


# Обработчик команды /get_chat_id
@dp.message(Command("get_chat_id"))
async def cmd_get_chat_id(message: Message):
    """Показывает ID текущего чата"""
    try:
        chat_id = message.chat.id
        chat_type = message.chat.type
        chat_title = message.chat.title or "Без названия"

        response = f"""
📋 Информация о чате:
• ID: `{chat_id}`
• Тип: {chat_type}
• Название: {chat_title}
"""
        await message.answer(response, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error getting chat ID: {e}")
        await message.answer("❌ Ошибка при получении ID чата")


# Также можно сделать обработчик для пересланных сообщений
@dp.message(F.forward_from_chat)
async def handle_forwarded_message(message: Message):
    """Обрабатывает пересланные сообщения и показывает ID исходного чата"""
    try:
        if message.forward_from_chat:
            chat_id = message.forward_from_chat.id
            chat_type = message.forward_from_chat.type
            chat_title = message.forward_from_chat.title or "Без названия"

            response = f"""
📋 Информация о пересланном чате:
• ID: `{chat_id}`
• Тип: {chat_type}
• Название: {chat_title}

💡 Чтобы добавить этот чат в мониторинг, используйте:
/monitor_chat
"""
            await message.answer(response, parse_mode="Markdown")
        else:
            await message.answer("❌ Это сообщение не содержит информации о чате")

    except Exception as e:
        logger.error(f"Error processing forwarded message: {e}")
        await message.answer("❌ Ошибка при обработке пересланного сообщения")


# Обработчик для любых сообщений с просьбой показать ID
@dp.message(F.text.contains("id чата"))
@dp.message(F.text.contains("chat id"))
@dp.message(F.text.contains("ID чата"))
async def handle_chat_id_request(message: Message):
    """Отвечает на запросы о ID чата"""
    chat_id = message.chat.id
    chat_type = message.chat.type
    chat_title = message.chat.title or "Без названия"

    response = f"""
💡 ID этого чата: `{chat_id}`
Тип: {chat_type}
Название: {chat_title}

Для полной информации используйте /get_chat_id
"""
    await message.answer(response, parse_mode="Markdown")


# Обработчик команды /monitor_chat
@dp.message(Command("monitor_chat"))
async def cmd_monitor_chat(message: Message):
    try:
        chat_id = str(message.chat.id)
        chat_name = message.chat.title or "Без названия"

        if db.add_monitored_chat(chat_id, chat_name):
            chat_messages[chat_id] = []
            await message.answer(f"✅ Чат '{chat_name}' добавлен в мониторинг")
        else:
            await message.answer("❌ Ошибка при добавлении чата в мониторинг")
    except Exception as e:
        logger.error(f"Error monitoring chat: {e}")
        await message.answer("❌ Ошибка при добавлении чата в мониторинг")


# Обработчик команды /stop_monitor
@dp.message(Command("stop_monitor"))
async def cmd_stop_monitor(message: Message):
    try:
        chat_id = str(message.chat.id)

        if db.remove_monitored_chat(chat_id):
            if chat_id in chat_messages:
                del chat_messages[chat_id]
            await message.answer("✅ Мониторинг чата остановлен")
        else:
            await message.answer("❌ Чат не найден в списке мониторинга")
    except Exception as e:
        logger.error(f"Error stopping monitor: {e}")
        await message.answer("❌ Ошибка при остановке мониторинга")


# Обработчик команды /list_chats
@dp.message(Command("list_chats"))
async def cmd_list_chats(message: Message):
    try:
        chats = db.get_monitored_chats()
        if not chats:
            await message.answer("📊 Нет отслеживаемых чатов")
            return

        chats_list = "\n".join([f"• {chat['chat_name']} ({chat['chat_id']})" for chat in chats])
        await message.answer(f"📊 Отслеживаемые чаты:\n{chats_list}")
    except Exception as e:
        logger.error(f"Error listing chats: {e}")
        await message.answer("❌ Ошибка при получении списка чатов")


# Обработчик команды /set_schedule
@dp.message(Command("set_schedule"))
async def cmd_set_schedule(message: Message):
    try:
        args = message.text.split()[1:]
        if not args:
            await message.answer("❌ Использование: /set_schedule <время>\nПример: /set_schedule 18:00")
            return

        post_time = args[0]

        # Проверяем формат времени
        try:
            datetime.strptime(post_time, "%H:%M")
        except ValueError:
            await message.answer("❌ Неверный формат времени. Используйте ЧЧ:ММ (например: 18:00)")
            return

        if CHANNEL_ID and db.set_posting_schedule(CHANNEL_ID, post_time):
            await message.answer(f"✅ Расписание установлено: ежедневно в {post_time}")
        else:
            await message.answer("❌ Ошибка установки расписания. Проверьте CHANNEL_ID в .env")
    except Exception as e:
        logger.error(f"Error setting schedule: {e}")
        await message.answer("❌ Ошибка при установке расписания")


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


# Обработчик команды /models
@dp.message(Command("models"))
async def cmd_models(message: Message):
    try:
        models_text = ai_client.get_available_models()
        await message.answer(models_text)
    except Exception as e:
        logger.error(f"Error getting models: {e}")
        await message.answer("❌ Ошибка при получении списка AI моделей")


# Обработчик ВСЕХ сообщений в отслеживаемых чатах
@dp.message(F.chat.id.in_([chat["chat_id"] for chat in db.get_monitored_chats()]))
async def handle_monitored_messages(message: Message):
    try:
        chat_id = str(message.chat.id)

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


# Функция для создания и отправки сводки
async def create_and_post_summary():
    """Создает сводку и публикует в канал"""
    try:
        if not CHANNEL_ID:
            logger.error("CHANNEL_ID не установлен в .env")
            return

        all_messages = []
        for chat_id, messages in chat_messages.items():
            if messages:
                all_messages.extend(messages)

        if not all_messages:
            logger.info("Нет сообщений для анализа")
            return

        # Анализируем сообщения с помощью AI
        analysis = ai_client.analyze_chat_messages(all_messages)

        # Форматируем для канала
        formatted_post = ai_client.format_for_channel(analysis)

        # Публикуем в канал
        await bot.send_message(chat_id=CHANNEL_ID, text=formatted_post)
        logger.info(f"Сводка опубликована в канал {CHANNEL_ID}")

        # Очищаем сообщения после публикации
        for chat_id in chat_messages:
            chat_messages[chat_id] = []

    except Exception as e:
        logger.error(f"Error creating and posting summary: {e}")


# Задача для периодического постинга
async def scheduled_posting():
    """Запускает периодическую проверку времени для постинга"""
    while True:
        try:
            schedule = db.get_posting_schedule()
            if schedule:
                current_time = datetime.now().strftime("%H:%M")
                if current_time == schedule["post_time"]:
                    await create_and_post_summary()
                    await asyncio.sleep(60)  # Ждем минуту чтобы не повторять
            await asyncio.sleep(30)  # Проверяем каждые 30 секунд
        except Exception as e:
            logger.error(f"Error in scheduled posting: {e}")
            await asyncio.sleep(60)


# Запуск бота
async def main():
    logger.info("Бот мониторинга запускается...")

    # Загружаем отслеживаемые чаты в память
    chats = db.get_monitored_chats()
    for chat in chats:
        chat_messages[chat["chat_id"]] = []

    stats = ai_client.get_stats()
    logger.info(f"AI моделей: {stats['ai_models']}")
    logger.info(f"Отслеживаемых чатов: {stats['monitored_chats']}")

    # Запускаем фоновую задачу постинга
    asyncio.create_task(scheduled_posting())

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())