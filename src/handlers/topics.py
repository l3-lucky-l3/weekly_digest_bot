import logging
from aiogram import Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

logger = logging.getLogger(__name__)


async def cmd_add_topic(message: Message, db):
    """Добавляет текущий топик для парсинга"""
    try:
        # Проверяем, что команда выполнена в топике форума
        if not hasattr(message, 'message_thread_id') or not message.message_thread_id:
            await message.answer(
                "❌ Эта команда должна быть выполнена в конкретопике форума\n"
                "💡 Перейдите в нужный топик и отправьте команду там"
            )
            return

        args = message.text.split()[1:]
        topic_name = ' '.join(args)

        topic_id = message.message_thread_id

        # Получаем название топика из reply_to_message если есть
        if not topic_name:
            topic_name = "Без названия"
            if (message.reply_to_message and
                    hasattr(message.reply_to_message, 'forum_topic_created') and
                    message.reply_to_message.forum_topic_created):
                topic_name = message.reply_to_message.forum_topic_created.name or "Без названия"

        if db.add_source_topic(topic_id, topic_name):
            response = f"✅ Топик добавлен в источники:\nID: <code>{topic_id}</code>\nНазвание: {topic_name}"
            await message.answer(response, parse_mode="HTML")
        else:
            await message.answer("❌ Ошибка при добавлении топика")

    except Exception as e:
        logger.error(f"Error adding topic: {e}")
        await message.answer("❌ Ошибка при добавлении топика")


async def cmd_delete_topic(message: Message, db):
    """Удаляет текущий топик из источников"""
    try:
        # Проверяем, что команда выполнена в топике форума
        if not hasattr(message, 'message_thread_id') or not message.message_thread_id:
            await message.answer(
                "❌ Эта команда должна быть выполнена в конкретном топике форума\n"
                "💡 Перейдите в нужный топик и отправьте команду там"
            )
            return

        topic_id = message.message_thread_id

        if db.remove_source_topic(topic_id):
            await message.answer(f"✅ Топик удален из источников\nID: <code>{topic_id}</code>", parse_mode="HTML")
        else:
            await message.answer(f"❌ Топик не найден в источниках\nID: <code>{topic_id}</code>", parse_mode="HTML")

    except Exception as e:
        logger.error(f"Error deleting topic: {e}")
        await message.answer("❌ Ошибка при удалении топика")


async def cmd_list_topics(message: Message, db):
    """Показывает список топиков-источников"""
    try:
        topics = db.get_source_topics()
        if not topics:
            await message.answer("📋 Нет добавленных топиков-источников")
            return

        topics_list = "\n".join([
            f"• ID: <code>{topic['topic_id']}</code>" +
            (f" - {topic['topic_name']}" if topic['topic_name'] else "")
            for topic in topics
        ])

        await message.answer(f"📋 Топики-источники:\n{topics_list}", parse_mode="HTML")

    except Exception as e:
        logger.error(f"Error listing topics: {e}")
        await message.answer("❌ Ошибка при получении списка топиков")


async def cmd_select_conductor_topic(message: Message, db):
    """Устанавливает текущий топик для публикации целей/блокеров (Пн)"""
    try:
        # Проверяем, что команда выполнена в топике форума
        if not hasattr(message, 'message_thread_id') or not message.message_thread_id:
            await message.answer(
                "❌ Эта команда должна быть выполнена в конкретном топике форума\n"
                "💡 Перейдите в нужный топик и отправьте команду там"
            )
            return

        args = message.text.split()[1:]
        topic_name = ' '.join(args)

        topic_id = message.message_thread_id

        # Получаем название топика из reply_to_message если есть
        if not topic_name:
            topic_name = "Conductor"
            if (message.reply_to_message and
                    hasattr(message.reply_to_message, 'forum_topic_created') and
                    message.reply_to_message.forum_topic_created):
                topic_name = message.reply_to_message.forum_topic_created.name or "Conductor"

        if db.set_system_topic("conductor", topic_id, topic_name):
            response = f"✅ Топик Conductor установлен:\nID: <code>{topic_id}</code>\nНазвание: {topic_name}"
            await message.answer(response, parse_mode="HTML")
        else:
            await message.answer("❌ Ошибка при установке топик Conductor")

    except Exception as e:
        logger.error(f"Error setting conductor topic: {e}")
        await message.answer("❌ Ошибка при установке топика Conductor")


async def cmd_select_announcements_topic(message: Message, db):
    """Устанавливает текущий топик для публикации дайджеста (Пт)"""
    try:
        # Проверяем, что команда выполнена в топике форума
        if not hasattr(message, 'message_thread_id') or not message.message_thread_id:
            await message.answer(
                "❌ Эта команда должна быть выполнена в конкретном топике форума\n"
                "💡 Перейдите в нужный топик и отправьте команду там"
            )
            return

        args = message.text.split()[1:]
        topic_name = ' '.join(args)

        topic_id = message.message_thread_id

        # Получаем название топика из reply_to_message если есть
        if not topic_name:
            topic_name = "Анонсы"
            if (message.reply_to_message and
                    hasattr(message.reply_to_message, 'forum_topic_created') and
                    message.reply_to_message.forum_topic_created):
                topic_name = message.reply_to_message.forum_topic_created.name or "Анонсы"

        if db.set_system_topic("announcements", topic_id, topic_name):
            response = f"✅ Топик Анонсы установлен:\nID: <code>{topic_id}</code>\nНазвание: {topic_name}"
            await message.answer(response, parse_mode="HTML")
        else:
            await message.answer("❌ Ошибка при установке топика Анонсы")

    except Exception as e:
        logger.error(f"Error setting announcements topic: {e}")
        await message.answer("❌ Ошибка при установке топика Анонсы")


async def cmd_show_config(message: Message, db, main_chat_id):
    """Показывает текущую конфигурацию топиков"""
    try:
        # Получаем топики-источники
        source_topics = db.get_source_topics()

        # Получаем системные топики
        conductor_topic = db.get_system_topic("conductor")
        announcements_topic = db.get_system_topic("announcements")

        # Получаем статистику сообщений из БД
        recent_messages = db.get_messages_for_period(days=7)
        total_messages = len(recent_messages)

        response = "⚙️ <b>Текущая конфигурация:</b>\n\n"

        response += "📥 <b>Топики-источники:</b>\n"
        if source_topics:
            for topic in source_topics:
                response += f"• ID: <code>{topic['topic_id']}</code>"
                if topic['topic_name']:
                    response += f" - {topic['topic_name']}"
                response += "\n"
        else:
            response += "❌ Не настроены\n"

        response += "\n📤 <b>Системные топики:</b>\n"

        if conductor_topic:
            response += f"• Conductor (Пн): ID <code>{conductor_topic['topic_id']}</code>"
            if conductor_topic['topic_name']:
                response += f" - {conductor_topic['topic_name']}"
            response += "\n"
        else:
            response += "• Conductor (Пн): ❌ Не настроен\n"

        if announcements_topic:
            response += f"• Анонсы (Пт): ID <code>{announcements_topic['topic_id']}</code>"
            if announcements_topic['topic_name']:
                response += f" - {announcements_topic['topic_name']}"
            response += "\n"
        else:
            response += "• Анонсы (Пт): ❌ Не настроен\n"

        response += f"\n💬 <b>Основной чат:</b> {main_chat_id or '❌ Не настроен'}"

        # Статистика сообщений из БД
        response += f"\n\n📊 <b>Сообщений в БД (за 7 дней):</b> {total_messages}"
        response += f"\n<b>Отслеживаемых топиков:</b> {len(source_topics)}"

        await message.answer(response, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Error showing config: {e}")
        await message.answer("❌ Ошибка при получении конфигурации")


def register_topic_handlers(dp: Dispatcher, db, main_chat_id):
    """Регистрирует обработчики управления топиками"""

    # Создаем замыкания для обработчиков, которым нужны дополнительные параметры
    async def wrapped_show_config(message: Message):
        await cmd_show_config(message, db, main_chat_id)

    async def wrapped_add_topic(message: Message):
        await cmd_add_topic(message, db)

    async def wrapped_delete_topic(message: Message):
        await cmd_delete_topic(message, db)

    async def wrapped_list_topics(message: Message):
        await cmd_list_topics(message, db)

    async def wrapped_select_conductor_topic(message: Message):
        await cmd_select_conductor_topic(message, db)

    async def wrapped_select_announcements_topic(message: Message):
        await cmd_select_announcements_topic(message, db)

    # Регистрируем обработчики
    dp.message.register(wrapped_add_topic, Command("addtopic"))
    dp.message.register(wrapped_delete_topic, Command("deletetopic"))
    dp.message.register(wrapped_list_topics, Command("listtopics"))
    dp.message.register(wrapped_select_conductor_topic, Command("selectconductortopic"))
    dp.message.register(wrapped_select_announcements_topic, Command("selectanouncestopic"))
    dp.message.register(wrapped_show_config, Command("showconfig"))
