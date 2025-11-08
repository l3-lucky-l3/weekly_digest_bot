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

# Проверка обязательных переменных
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен в .env файле")

if not MAIN_CHAT_ID:
    logger.warning("MAIN_CHAT_ID не установлен в .env файле")

if not ADMIN_CHAT_ID:
    logger.warning("ADMIN_CHAT_ID не установлен в .env файле")

# Инициализация компонентов
bot = Bot(token=BOT_TOKEN, timeout=60)
dp = Dispatcher()
db = Database()
ai_client = AIClient(db)
classification_service = ClassificationService(db, ai_client, batch_size=5)  # Количество сообщений разом посылаемых ИИ
posting_service = PostingService(db, ai_client, MAIN_CHAT_ID, ADMIN_CHAT_ID)
html_parser = HTMLParserService(db)


# Глобальные флаги состояния
class BotState:
    def __init__(self):
        self.processing_in_progress = False
        self.startup_processed = False
        self.last_message_processing_date = None
        self.last_cleanup_date = None


bot_state = BotState()


# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
async def safe_process_unprocessed_messages():
    """Безопасная обработка сообщений в отдельной задаче"""
    try:
        logger.info("🔄 Начало безопасной обработки сообщений...")
        processed_count = await classification_service.process_unprocessed_messages()
        logger.info(f"✅ Обработка сообщений завершена. Обработано: {processed_count}")
        return processed_count
    except Exception as e:
        logger.error(f"❌ Ошибка при обработке сообщений: {e}")
        return 0
    finally:
        bot_state.processing_in_progress = False
        logger.info("🔓 Снят флаг processing_in_progress")


async def safe_create_monday_post():
    """Безопасное создание понедельничного поста"""
    try:
        # Сначала обрабатываем необработанные сообщения
        if not bot_state.processing_in_progress:
            logger.info("🔄 Перед созданием поста обрабатываем необработанные сообщения...")
            bot_state.processing_in_progress = True
            await safe_process_unprocessed_messages()

        # Затем создаем пост
        success = await posting_service.create_monday_post(bot)
        if success:
            logger.info("✅ Понедельничный пост создан успешно")
        else:
            logger.error("❌ Ошибка при создании понедельничного поста")
        return success
    except Exception as e:
        logger.error(f"❌ Ошибка при создании понедельничного поста: {e}")
        return False


async def safe_create_friday_digest():
    """Безопасное создание пятничного дайджеста"""
    try:
        # Сначала обрабатываем необработанные сообщения
        if not bot_state.processing_in_progress:
            logger.info("🔄 Перед созданием дайджеста обрабатываем необработанные сообщения...")
            bot_state.processing_in_progress = True
            await safe_process_unprocessed_messages()

        # Затем создаем дайджест
        success = await posting_service.create_friday_digest(bot)
        if success:
            logger.info("✅ Пятничный дайджест создан успешно")
        else:
            logger.error("❌ Ошибка при создании пятничного дайджеста")
        return success
    except Exception as e:
        logger.error(f"❌ Ошибка при создании пятничного дайджеста: {e}")
        return False


async def safe_cleanup_messages():
    """Безопасная очистка сообщений"""
    try:
        deleted_count = db.cleanup_old_messages(days=MESSAGE_RETENTION_DAYS)
        if deleted_count > 0:
            logger.info(f"✅ Автоочистка БД: удалено {deleted_count} старых сообщений")
        else:
            logger.info("✅ Нечего очищать")
        return deleted_count
    except Exception as e:
        logger.error(f"❌ Ошибка при очистке БД: {e}")
        return 0


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
    while True:
        try:
            now = datetime.now()
            current_date = now.date()
            current_time = now.strftime("%H:%M")
            weekday = now.strftime("%A")

            # Обработка при первом запуске бота
            if not bot_state.startup_processed and not bot_state.processing_in_progress:
                logger.info("🚀 Запуск первоначальной обработки накопленных сообщений...")
                bot_state.processing_in_progress = True
                asyncio.create_task(safe_process_unprocessed_messages())
                bot_state.startup_processed = True
                await asyncio.sleep(5)

            # Обработка необработанных сообщений - раз в сутки в 02:00
            elif current_time == "02:00" and not bot_state.processing_in_progress:
                if bot_state.last_message_processing_date != current_date:
                    logger.info("🔄 Запуск ежедневной обработки сообщений...")
                    bot_state.processing_in_progress = True
                    asyncio.create_task(safe_process_unprocessed_messages())
                    bot_state.last_message_processing_date = current_date
                    await asyncio.sleep(60)

            # Понедельник 10:00 - цели/блокеры
            elif weekday == "Monday" and current_time == "10:00":
                logger.info("📅 Запуск создания понедельничного поста...")
                asyncio.create_task(safe_create_monday_post())
                await asyncio.sleep(60)

            # Пятница 19:00 - Weekly Digest
            elif weekday == "Friday" and current_time == "19:00":
                logger.info("📊 Запуск создания пятничного дайджеста...")
                asyncio.create_task(safe_create_friday_digest())
                await asyncio.sleep(60)

            # Ежедневная очистка в 03:00
            elif current_time == "03:00":
                if bot_state.last_cleanup_date != current_date:
                    logger.info("🧹 Запуск ежедневной очистки БД...")
                    asyncio.create_task(safe_cleanup_messages())
                    bot_state.last_cleanup_date = current_date
                    await asyncio.sleep(60)

            await asyncio.sleep(30)

        except Exception as e:
            logger.error(f"❌ Error in scheduled posting: {e}")
            bot_state.processing_in_progress = False
            await asyncio.sleep(60)


# === ЗАПУСК БОТА ===
async def main():
    """Основная функция запуска бота"""
    try:
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
        logger.info("🤖 Бот начинает polling...")
        await dp.start_polling(bot, skip_updates=True)  # skip_updates чтобы избежать обработки старых сообщений
    finally:
        await ai_client.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⏹ Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}")
