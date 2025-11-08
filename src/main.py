import os
import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher

from db import Database
from ai_client import AIClient
from handlers.commands import register_command_handlers
from handlers.topics import register_topic_handlers
from utils.filters import SourceTopicsFilter
from services.posting_service import PostingService
from services.html_parser import HTMLParserService


# === КОНФИГУРАЦИЯ ===
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Константы
MESSAGE_RETENTION_DAYS = 7
BOT_TOKEN = os.getenv("BOT_TOKEN")
MAIN_CHAT_ID = os.getenv("MAIN_CHAT_ID")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# Проверка обязательных переменных
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен в .env файле")

if not MAIN_CHAT_ID:
    logger.warning("MAIN_CHAT_ID не установлен в .env файле")

if not ADMIN_CHAT_ID:
    logger.warning("ADMIN_CHAT_ID не установлен в .env файле")

# Инициализация компонентов
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
db = Database()
ai_client = AIClient()
posting_service = PostingService(db, ai_client, MAIN_CHAT_ID, ADMIN_CHAT_ID)
html_parser = HTMLParserService(db)


# === РЕГИСТРАЦИЯ ОБРАБОТЧИКОВ ===
def register_all_handlers():
    """Регистрирует все обработчики бота"""
    register_command_handlers(dp, db, bot, ai_client, posting_service, html_parser)
    register_topic_handlers(dp, db, MAIN_CHAT_ID)

    # Регистрация кастомного фильтра для топиков-источников
    dp.message.register(
        handle_source_topic_messages,
        SourceTopicsFilter(db, MAIN_CHAT_ID)
    )


# === ОБРАБОТЧИКИ СООБЩЕНИЙ ИЗ ТОПИКОВ ===
async def handle_source_topic_messages(message):
    """Обрабатывает сообщения из топиков-источников"""
    await process_topic_message(message)


async def process_topic_message(message):
    """Обрабатывает и сохраняет сообщение из топика в БД"""
    try:
        topic_id = message.message_thread_id

        # Сохраняем только текстовые сообщения без команд
        if message.text and not message.text.startswith('/'):
            message_data = {
                'message_id': message.message_id,
                'topic_id': topic_id,
                'message_text': message.text,
                'thread_id': None,
                'parent_message_id': message.reply_to_message.message_id if message.reply_to_message and message.reply_to_message.message_id != topic_id else None,
                'classification_id': None
            }

            if db.save_message(message_data):
                logger.debug(f"Сообщение сохранено в БД для топика {topic_id}: {message.text[:50]}...")
            else:
                logger.error(f"Ошибка сохранения сообщения в БД для топика {topic_id}")

    except Exception as e:
        logger.error(f"Error processing topic message: {e}")


# === ТРЕХСТУПЕНЧАТАЯ КЛАССИФИКАЦИЯ ===
async def process_unprocessed_messages():
    """Обрабатывает необработанные сообщения трехступенчатым методом"""
    try:
        unprocessed_messages = db.get_unprocessed_messages()
        if not unprocessed_messages:
            return

        active_threads = db.get_active_threads_with_messages(days=7)

        for message in unprocessed_messages:
            await three_step_classification(message, active_threads)

    except Exception as e:
        logger.error(f"Ошибка обработки необработанных сообщений: {e}")


async def three_step_classification(message_data, active_threads):
    """Трехступенчатый процесс классификации сообщения"""
    try:
        message_id = message_data['message_id']
        message_text = message_data['message_text']

        # Шаг 1: Проверка ответа/реплая
        if message_data['parent_message_id']:
            parent_thread = db.get_message_thread_by_parent(message_data['parent_message_id'])
            if parent_thread:
                db.update_message_thread(message_id, parent_thread['thread_id'], parent_thread['classification_id'])
                logger.info(f"Сообщение {message_id} привязано к треду {parent_thread['thread_id']} (наследование)")
                return

        # Шаг 2: Семантический слинг
        sling_result = await ai_client.semantic_sling_schema_c(message_text, active_threads)
        if sling_result['related'] and sling_result['thread_id']:
            thread = db.get_thread_by_id(sling_result['thread_id'])
            if thread:
                db.update_message_thread(message_id, sling_result['thread_id'], thread['classification_id'])
                logger.info(
                    f"Сообщение {message_id} привязано к треду {sling_result['thread_id']} (семантический слинг)")
                return

        # Шаг 3: Классификация новой сущности
        classification_result = await ai_client.classify_message_schema_b(message_text)
        if classification_result['classification'] in ['goal', 'blocker']:
            thread_id = db.create_thread(
                classification_result['title'] or message_text[:50],
                classification_result['classification']
            )
            if thread_id > 0:
                db.update_message_thread(message_id, thread_id, classification_result['classification'])
                logger.info(
                    f"Создан новый тред {thread_id} для сообщения {message_id} ({classification_result['classification']})")
            else:
                logger.error(f"Ошибка создания треда для сообщения {message_id}")
        else:
            # Помечаем как обработанное даже если не классифицировано
            db.update_message_thread(message_id, None, 'other')
            logger.info(f"Сообщение {message_id} помечено как 'other'")

    except Exception as e:
        logger.error(f"Ошибка трехступенчатой классификации для сообщения {message_data['message_id']}: {e}")


# === ПЛАНИРОВЩИК ЗАДАЧ ===
async def scheduled_posting():
    """Запускает периодическую проверку времени для постинга и обработки"""
    while True:
        try:
            now = datetime.now()
            current_time = now.strftime("%H:%M")
            weekday = now.strftime("%A")

            # Каждые 5 минут обрабатываем необработанные сообщения
            if current_time.endswith(
                    (':00', ':05', ':10', ':15', ':20', ':25', ':30', ':35', ':40', ':45', ':50', ':55')):
                await process_unprocessed_messages()

            # Понедельник 10:00 - цели/блокеры
            if weekday == "Monday" and current_time == "10:00":
                await posting_service.create_monday_post(bot)
                await asyncio.sleep(60)

            # Пятница 19:00 - Weekly Digest
            elif weekday == "Friday" and current_time == "19:00":
                await posting_service.create_friday_digest(bot)
                await asyncio.sleep(60)

            # Ежедневная очистка в 03:00
            elif current_time == "03:00":
                deleted_count = db.cleanup_old_messages(days=MESSAGE_RETENTION_DAYS)
                if deleted_count > 0:
                    logger.info(f"Автоочистка БД: удалено {deleted_count} старых сообщений")
                await asyncio.sleep(60)

            await asyncio.sleep(30)

        except Exception as e:
            logger.error(f"Error in scheduled posting: {e}")
            await asyncio.sleep(60)


# === ЗАПУСК БОТА ===
async def main():
    """Основная функция запуска бота"""
    logger.info("🚀 Weekly-дайджест бот запускается...")

    # Показываем конфигурацию при запуске
    source_topics = db.get_source_topics()
    conductor_topic = db.get_system_topic("conductor")
    announcements_topic = db.get_system_topic("announcements")
    recent_messages = db.get_messages_for_period(days=MESSAGE_RETENTION_DAYS)

    logger.info(f"Основной чат: {MAIN_CHAT_ID}")
    logger.info(f"Топиков-источников: {len(source_topics)}")
    logger.info(f"Топик Conductor: {conductor_topic['topic_id'] if conductor_topic else 'Не настроен'}")
    logger.info(f"Топик Анонсы: {announcements_topic['topic_id'] if announcements_topic else 'Не настроен'}")
    logger.info(f"Сообщений в БД за {MESSAGE_RETENTION_DAYS} дней: {len(recent_messages)}")

    stats = ai_client.get_stats()
    logger.info(f"AI моделей: {stats['ai_models']}")

    # Регистрируем все обработчики
    register_all_handlers()

    # Запускаем фоновую задачу постинга
    asyncio.create_task(scheduled_posting())

    # Запускаем бота
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
