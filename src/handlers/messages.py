import logging
from aiogram import Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message


logger = logging.getLogger(__name__)


async def cmd_test_post(message: Message, bot, db, ai_client, main_chat_id):
    """Тестовая команда для отправки примеров постов"""
    try:
        args = message.text.split()[1:]
        post_type = args[0] if args else "monday"

        if post_type == "monday":
            await send_test_monday_post(message, bot, db, ai_client, main_chat_id)
        elif post_type == "friday":
            await send_test_friday_digest(message, bot, db, ai_client, main_chat_id)
        else:
            await message.answer(
                "❌ Использование: /test_post <тип>\n"
                "Типы:\n"
                "• monday - тест понедельничного поста\n"
                "• friday - тест пятничного дайджеста\n"
                "Пример: /test_post monday"
            )

    except Exception as e:
        logger.error(f"Error in test_post command: {e}")
        await message.answer("❌ Ошибка при создании тестового поста")


async def send_test_monday_post(message: Message, bot, db, ai_client, main_chat_id):
    """Отправляет тестовый понедельничный пост"""
    try:
        # Получаем сообщения из БД за последнюю неделю
        recent_messages = db.get_messages_for_period(days=7)

        if not recent_messages:
            # Если нет сообщений в БД, используем тестовые
            test_messages = [
                "Нужно доработать авторизацию в проекте",
                "Проблемы с производительностью на мобильных устройствах",
                "Ищем фронтенд разработчика в команду",
                "Обсуждаем дизайн главной страницы"
            ]
            message_texts = test_messages
            logger.info("Используются тестовые сообщения для демонстрации")
        else:
            message_texts = [msg['message_text'] for msg in recent_messages if msg['message_text']]

        # Используем промпт из файла
        prompt = ai_client.load_prompt("monday")
        prompt += f"\n\nСообщения из топиков:\n{'; '.join(message_texts)}"

        post_text = await ai_client.send_request_with_retry(prompt)

        # Пытаемся отправить в системный топик Conductor
        conductor_topic = db.get_system_topic("conductor")
        if conductor_topic:
            try:
                await bot.send_message(
                    chat_id=main_chat_id,
                    message_thread_id=conductor_topic['topic_id'],
                    text=post_text,
                    parse_mode="HTML"
                )
                await message.answer(f"✅ Тестовый пост отправлен в топик Conductor (ID: {conductor_topic['topic_id']})")
            except Exception as e:
                logger.error(f"Error sending to conductor topic: {e}")
                await message.answer(f"❌ Ошибка отправки в топик Conductor: {e}")
        else:
            await message.answer("❌ Топик Conductor не настроен. Используйте /selectconductortopic")

        logger.info("Тестовый понедельничный пост создан")

    except Exception as e:
        logger.error(f"Error sending test Monday post: {e}")
        await message.answer("❌ Ошибка при создании тестового понедельничного поста")


async def send_test_friday_digest(message: Message, bot, db, ai_client, main_chat_id):
    """Отправляет тестовый пятничный дайджест"""
    try:
        # Получаем сообщения из БД за последнюю неделю
        recent_messages = db.get_messages_for_period(days=7)

        if not recent_messages:
            # Если нет сообщений в БД, используем тестовые
            test_messages = [
                "Запустили новую фичу авторизации",
                "Обсуждаем дизайн главной страницы",
                "Проблемы с производительностью на мобильных устройствах",
                "Ищем фронтенд разработчика в команду",
                "Провели успешный деплой в продакшен"
            ]
            message_texts = test_messages
            logger.info("Используются тестовые сообщения для демонстрации")
        else:
            message_texts = [msg['message_text'] for msg in recent_messages if msg['message_text']]

        # Используем промпт из файла
        prompt = ai_client.load_prompt("friday")
        prompt += f"\n\nСообщения из топиков:\n{'; '.join(message_texts)}"

        post_text = await ai_client.send_request_with_retry(prompt)

        # Пытаемся отправить в системный топик Анонсы
        announcements_topic = db.get_system_topic("announcements")
        if announcements_topic:
            try:
                await bot.send_message(
                    chat_id=main_chat_id,
                    message_thread_id=announcements_topic['topic_id'],
                    text=post_text,
                    parse_mode="HTML"
                )
                await message.answer(
                    f"✅ Тестовый дайджест отправлен в топик Анонсы (ID: {announcements_topic['topic_id']})")
            except Exception as e:
                logger.error(f"Error sending to announcements topic: {e}")
                await message.answer(f"❌ Ошибка отправки в топик Анонсы: {e}")
        else:
            await message.answer("❌ Топик Анонсы не настроен. Используйте /selectanouncestopic")

        logger.info("Тестовый пятничный дайджест создан")

    except Exception as e:
        logger.error(f"Error sending test Friday digest: {e}")
        await message.answer("❌ Ошибка при создании тестового пятничного дайджеста")


def register_message_handlers(dp: Dispatcher, db, main_chat_id, bot, ai_client):
    """Регистрирует обработчики сообщений"""

    # Создаем замыкание для обработчика тестовых постов
    async def wrapped_test_post(message: Message):
        await cmd_test_post(message, bot, db, ai_client, main_chat_id)

    # Обработчик тестовых постов
    dp.message.register(wrapped_test_post, Command("test_post"))

