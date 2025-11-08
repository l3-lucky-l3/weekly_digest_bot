# from aiogram.client.session.aiohttp import AiohttpSession  # TODO del | this for pythonanywhere
#
# # if not MAIN_CHAT_ID:
# #     logger.warning("MAIN_CHAT_ID не установлен в .env файле")
#
#
# # TODO del | this for pythonanywhere
# PROXY_URL = "http://proxy.server:3128"
#
#
# def create_bot_with_proxy():
#     """Создает бота с настройкой прокси"""
#     session = None
#     if PROXY_URL:
#         session = AiohttpSession(proxy=PROXY_URL)
#         logger.info("Используется прокси для подключения к Telegram")
#
#     return Bot(token=BOT_TOKEN, session=session)
#
#
# # Инициализация компонентов
# bot = create_bot_with_proxy()  # TODO del | this for pythonanywhere
# TODO !

import os
import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession  # TODO del | this for pythonanywhere

from db import Database
from ai_client import AIClient
from handlers.commands import register_command_handlers
from handlers.topics import register_topic_handlers
from utils.filters import SourceTopicsFilter
from services.posting_service import PostingService
from services.html_parser import HTMLParserService
from services.classification_service import ClassificationService


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
processing_in_progress = False

# Проверка обязательных переменных
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен в .env файле")

if not MAIN_CHAT_ID:
    logger.warning("MAIN_CHAT_ID не установлен в .env файле")

if not ADMIN_CHAT_ID:
    logger.warning("ADMIN_CHAT_ID не установлен в .env файле")


# TODO del | this for pythonanywhere
PROXY_URL = "http://proxy.server:3128"


def create_bot_with_proxy():
    """Создает бота с настройкой прокси"""
    session = None
    if PROXY_URL:
        session = AiohttpSession(proxy=PROXY_URL)
        logger.info("Используется прокси для подключения к Telegram")

    return Bot(token=BOT_TOKEN, session=session)


# Инициализация компонентов
bot = create_bot_with_proxy()  # TODO del | this for pythonanywhere
dp = Dispatcher()
db = Database()
ai_client = AIClient()
classification_service = ClassificationService(db, ai_client, batch_size=5)
posting_service = PostingService(db, ai_client, MAIN_CHAT_ID, ADMIN_CHAT_ID)
html_parser = HTMLParserService(db)


# === РЕГИСТРАЦИЯ ОБРАБОТЧИКОВ ===
def register_all_handlers():
    """Регистрирует все обработчики бота"""
    register_command_handlers(dp, db, bot, ai_client, posting_service, html_parser, classification_service)
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


# === ПЛАНИРОВЩИК ЗАДАЧ ===
async def scheduled_posting():
    """Запускает периодическую проверку времени для постинга и обработки"""
    # Переменные для отслеживания выполнения ежедневных задач
    last_message_processing_date = None
    last_cleanup_date = None
    startup_processed = False  # Флаг для обработки при запуске
    processing_in_progress = False  # Флаг чтобы избежать параллельной обработки

    while True:
        try:
            now = datetime.now()
            current_date = now.date()  # Текущая дата без времени
            current_time = now.strftime("%H:%M")
            weekday = now.strftime("%A")

            # Обработка при первом запуске бота
            if not startup_processed and not processing_in_progress:
                logger.info("Запуск первоначальной обработки накопленных сообщений...")
                processing_in_progress = True
                # Запускаем в отдельной задаче чтобы не блокировать бота
                asyncio.create_task(
                    safe_process_unprocessed_messages(classification_service)
                )
                startup_processed = True
                await asyncio.sleep(5)

            # Обработка необработанных сообщений - раз в сутки в 02:00
            elif current_time == "02:00" and not processing_in_progress:
                if last_message_processing_date != current_date:
                    logger.info("Запуск ежедневной обработки сообщений...")
                    processing_in_progress = True
                    asyncio.create_task(
                        safe_process_unprocessed_messages(classification_service,
                                                        last_message_processing_date)
                    )
                    last_message_processing_date = current_date
                    await asyncio.sleep(60)

            # Понедельник 10:00 - цели/блокеры
            elif weekday == "Monday" and current_time == "10:00":
                logger.info("Запуск создания понедельничного поста...")
                asyncio.create_task(safe_create_monday_post(posting_service, bot))
                await asyncio.sleep(60)

            # Пятница 19:00 - Weekly Digest
            elif weekday == "Friday" and current_time == "19:00":
                logger.info("Запуск создания пятничного дайджеста...")
                asyncio.create_task(safe_create_friday_digest(posting_service, bot))
                await asyncio.sleep(60)

            # Ежедневная очистка в 03:00
            elif current_time == "03:00":
                if last_cleanup_date != current_date:
                    logger.info("Запуск ежедневной очистки БД...")
                    # Очистка БД обычно быстрая, но на всякий случай тоже в отдельной задаче
                    asyncio.create_task(safe_cleanup_messages(db, MESSAGE_RETENTION_DAYS))
                    last_cleanup_date = current_date
                    await asyncio.sleep(60)

            await asyncio.sleep(30)

        except Exception as e:
            logger.error(f"Error in scheduled posting: {e}")
            processing_in_progress = False
            await asyncio.sleep(60)


async def safe_process_unprocessed_messages(classification_service, date_tracker=None):
    """Безопасная обработка сообщений в отдельной задаче"""
    try:
        processed_count = await classification_service.process_unprocessed_messages()
        logger.info(f"✅ Обработка сообщений завершена. Обработано: {processed_count}")
    except Exception as e:
        logger.error(f"❌ Ошибка при обработке сообщений: {e}")
    finally:
        # Сбрасываем флаг независимо от результата
        global processing_in_progress
        processing_in_progress = False


async def safe_create_monday_post(posting_service, bot):
    """Безопасное создание понедельничного поста"""
    try:
        success = await posting_service.create_monday_post(bot)
        if success:
            logger.info("✅ Понедельничный пост создан успешно")
        else:
            logger.error("❌ Ошибка при создании понедельничного поста")
    except Exception as e:
        logger.error(f"❌ Ошибка при создании понедельничного поста: {e}")


async def safe_create_friday_digest(posting_service, bot):
    """Безопасное создание пятничного дайджеста"""
    try:
        success = await posting_service.create_friday_digest(bot)
        if success:
            logger.info("✅ Пятничный дайджест создан успешно")
        else:
            logger.error("❌ Ошибка при создании пятничного дайджеста")
    except Exception as e:
        logger.error(f"❌ Ошибка при создании пятничного дайджеста: {e}")


async def safe_cleanup_messages(db, retention_days):
    """Безопасная очистка сообщений"""
    try:
        deleted_count = db.cleanup_old_messages(days=retention_days)
        if deleted_count > 0:
            logger.info(f"✅ Автоочистка БД: удалено {deleted_count} старых сообщений")
        else:
            logger.info("✅ Нечего очищать")
    except Exception as e:
        logger.error(f"❌ Ошибка при очистке БД: {e}")


# === ЗАПУСК БОТА ===
async def main():
    """Основная функция запуска бота"""
    logger.info("🚀 Weekly-дайджест бот запускается...")

    # Показываем конфигурацию при запуске
    source_topics = db.get_source_topics()
    announce_topic = db.get_system_topic("announce")
    digest_topic = db.get_system_topic("digest")
    recent_messages = db.get_messages_for_period(days=MESSAGE_RETENTION_DAYS)

    logger.info(f"Основной чат: {MAIN_CHAT_ID}")
    logger.info(f"Топиков-источников: {len(source_topics)}")
    logger.info(f"Топик Анонсы: {announce_topic['topic_id'] if announce_topic else 'Не настроен'}")
    logger.info(f"Топик Дайджесты: {digest_topic['topic_id'] if digest_topic else 'Не настроен'}")
    logger.info(f"Сообщений в БД за {MESSAGE_RETENTION_DAYS} дней: {len(recent_messages)}")

    stats = ai_client.get_stats()
    logger.info(f"AI моделей: {stats['ai_models']}")

    # Статистика классификации
    classification_stats = classification_service.get_classification_stats()
    if classification_stats:
        logger.info(f"Статистика классификации: {classification_stats['processed']}/{classification_stats['total_messages']} обработано ({classification_stats['processing_rate']})")

    # Регистрируем все обработчики
    register_all_handlers()

    # Запускаем фоновую задачу постинга
    asyncio.create_task(scheduled_posting())

    # Запускаем бота
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
