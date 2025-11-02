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
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Инициализация клиентов
ai_client = AIClient()
db = Database()

# Токены из .env
BOT_TOKEN = os.getenv("BOT_TOKEN")
MAIN_CHAT_ID = os.getenv("MAIN_CHAT_ID")  # Основная супергруппа

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен в .env файле")

if not MAIN_CHAT_ID:
    logger.warning("MAIN_CHAT_ID не установлен в .env файле")

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Временное хранилище сообщений из топиков
topic_messages = {}


# Обработчик команды /start
@dp.message(Command("start"))
async def cmd_start(message: Message):
    welcome_text = """
🚀 Weekly-дайджест бот

Мониторинг топиков сообщества и создание еженедельных дайджестов.

📅 Расписание:
• Пн 10:00 - цели/блокеры недели (в топик Conductor)
• Пт 19:00 - Weekly Digest (в топик Анонсы)

📋 Управление топиками:
/addtopic - добавить текущий топик для мониторинга
/deletetopic - удалить текущий топик из мониторинга
/listtopics - список отслеживаемых топиков
/selectconductortopic - установить текущий топик для постов в понедельник
/selectanouncestopic - установить текущий топик для дайджестов в пятницу
/showconfig - показать текущую конфигурацию

🤖 Управление AI моделями:
/add_model <название> <модель> - добавить AI модель
/remove_model <название> - удалить AI модель
/models - список AI моделей

🔧 Утилиты:
/get_chat_id - показать ID текущего чата/топика
/test_post <тип> - тестовая отправка поста

💡 Команды управления топиками должны выполняться внутри нужного топика!
"""
    await message.answer(welcome_text)


# Обработчик команды /get_chat_id
@dp.message(Command("get_chat_id"))
async def cmd_get_chat_id(message: Message):
    """Показывает ID текущего чата и топика"""
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
<b>ID чата:</b> <code>{chat_id}</code>
<b>Название:</b> {chat_title}"""

        # Если это топик форума, показываем ID топика
        if hasattr(message, 'message_thread_id') and message.message_thread_id:
            response += f"\n<b>ID топика:</b> <code>{message.message_thread_id}</code>"

            # Проверяем, является ли этот топик источником
            source_topics = db.get_source_topics()
            is_source = any(topic['topic_id'] == message.message_thread_id for topic in source_topics)
            response += f"\n<b>Статус:</b> {'✅ Источник' if is_source else '❌ Не источник'}"

            # Проверяем, является ли системным топиком
            conductor_topic = db.get_system_topic("conductor")
            announcements_topic = db.get_system_topic("announcements")

            if conductor_topic and conductor_topic['topic_id'] == message.message_thread_id:
                response += f"\n<b>Назначение:</b> 🎯 Conductor (понедельник)"
            elif announcements_topic and announcements_topic['topic_id'] == message.message_thread_id:
                response += f"\n<b>Назначение:</b> 📢 Анонсы (пятница)"

        response += f"""

💡 <b>Команды для этого топика:</b>
/addtopic - добавить в источники
/deletetopic - удалить из источников
/selectconductortopic - установить как Conductor
/selectanouncestopic - установить как Анонсы
"""
        await message.answer(response, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Error getting chat ID: {e}")
        await message.answer("❌ Ошибка при получении ID чата")


# Обработчик для пересланных сообщений
@dp.message(F.forward_from_chat)
async def handle_forwarded_message(message: Message):
    """Обрабатывает пересланные сообщения и показывает ID чата/канала/топика"""
    try:
        if message.forward_from_chat:
            chat = message.forward_from_chat

            response = f"""
📋 <b>Информация о пересланном чате/канале:</b>

<b>Тип:</b> {chat.type}
<b>ID чата:</b> <code>{chat.id}</code>
<b>Название:</b> {chat.title or "Без названия"}
"""

            # Если есть информация о топике
            if hasattr(message, 'forward_from_message_id'):
                response += f"<b>ID сообщения:</b> {message.forward_from_message_id}\n"

            response += f"""
💡 <b>Команды для добавления:</b>
<code>/addtopic {chat.id}</code> - добавить весь чат как источник

💡 <i>Или используйте ID конкретного топика из настроек форума</i>
"""
            await message.answer(response, parse_mode="HTML")
        else:
            await message.answer("❌ Это не пересланное сообщение из чата/канала")

    except Exception as e:
        logger.error(f"Error processing forwarded message: {e}")
        await message.answer("❌ Ошибка при обработке пересланного сообщения")


# === КОМАНДЫ УПРАВЛЕНИЯ ТОПИКАМИ ===

@dp.message(Command("addtopic"))
async def cmd_add_topic(message: Message):
    """Добавляет текущий топик для парсинга"""
    try:
        # Проверяем, что команда выполнена в топике форума
        if not hasattr(message, 'message_thread_id') or not message.message_thread_id:
            await message.answer(
                "❌ Эта команда должна быть выполнена в конкретопике форума\n"
                "💡 Перейдите в нужный топик и отправьте команду там"
            )
            return

        topic_id = message.message_thread_id

        args = message.text.split()[1:]
        if args:
            topic_name = args[0]
        else:
            topic_name = message.reply_to_message.forum_topic_created.name or "Без названия"

        if db.add_source_topic(topic_id, topic_name):
            # Инициализируем хранилище для этого топика
            topic_messages[topic_id] = []

            response = f"✅ Топик добавлен в источники:\nID: <code>{topic_id}</code>\nНазвание: {topic_name}"
            await message.answer(response, parse_mode="HTML")
        else:
            await message.answer("❌ Ошибка при добавлении топика")

    except Exception as e:
        logger.error(f"Error adding topic: {e}")
        await message.answer("❌ Ошибка при добавлении топика")


@dp.message(Command("deletetopic"))
async def cmd_delete_topic(message: Message):
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
            # Удаляем из временного хранилища
            if topic_id in topic_messages:
                del topic_messages[topic_id]
            await message.answer(f"✅ Топик удален из источников\nID: <code>{topic_id}</code>", parse_mode="HTML")
        else:
            await message.answer(f"❌ Топик не найден в источниках\nID: <code>{topic_id}</code>", parse_mode="HTML")

    except Exception as e:
        logger.error(f"Error deleting topic: {e}")
        await message.answer("❌ Ошибка при удалении топика")


@dp.message(Command("listtopics"))
async def cmd_list_topics(message: Message):
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


@dp.message(Command("selectconductortopic"))
async def cmd_select_conductor_topic(message: Message):
    """Устанавливает текущий топик для публикации целей/блокеров (Пн)"""
    try:
        # Проверяем, что команда выполнена в топике форума
        if not hasattr(message, 'message_thread_id') or not message.message_thread_id:
            await message.answer(
                "❌ Эта команда должна быть выполнена в конкретном топике форума\n"
                "💡 Перейдите в нужный топик и отправьте команду там"
            )
            return

        topic_id = message.message_thread_id

        args = message.text.split()[1:]
        if args:
            topic_name = args[0]
        else:
            topic_name = message.reply_to_message.forum_topic_created.name or "Conductor"

        if db.set_system_topic("conductor", topic_id, topic_name):
            response = f"✅ Топик Conductor установлен:\nID: <code>{topic_id}</code>\nНазвание: {topic_name}"
            await message.answer(response, parse_mode="HTML")
        else:
            await message.answer("❌ Ошибка при установке топика Conductor")

    except Exception as e:
        logger.error(f"Error setting conductor topic: {e}")
        await message.answer("❌ Ошибка при установке топика Conductor")


@dp.message(Command("selectanouncestopic"))
async def cmd_select_announcements_topic(message: Message):
    """Устанавливает текущий топик для публикации дайджеста (Пт)"""
    try:
        # Проверяем, что команда выполнена в топике форума
        if not hasattr(message, 'message_thread_id') or not message.message_thread_id:
            await message.answer(
                "❌ Эта команда должна быть выполнена в конкретном топике форума\n"
                "💡 Перейдите в нужный топик и отправьте команду там"
            )
            return

        topic_id = message.message_thread_id

        args = message.text.split()[1:]
        if args:
            topic_name = args[0]
        else:
            topic_name = message.reply_to_message.forum_topic_created.name or "Анонсы"

        if db.set_system_topic("announcements", topic_id, topic_name):
            response = f"✅ Топик Анонсы установлен:\nID: <code>{topic_id}</code>\nНазвание: {topic_name}"
            await message.answer(response, parse_mode="HTML")
        else:
            await message.answer("❌ Ошибка при установке топика Анонсы")

    except Exception as e:
        logger.error(f"Error setting announcements topic: {e}")
        await message.answer("❌ Ошибка при установке топика Анонсы")


@dp.message(Command("showconfig"))
async def cmd_show_config(message: Message):
    """Показывает текущую конфигурацию топиков"""
    try:
        # Получаем топики-источники
        source_topics = db.get_source_topics()

        # Получаем системные топики
        conductor_topic = db.get_system_topic("conductor")
        announcements_topic = db.get_system_topic("announcements")

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

        response += f"\n💬 <b>Основной чат:</b> {MAIN_CHAT_ID or '❌ Не настроен'}"

        # Статистика сообщений
        total_messages = sum(len(messages) for messages in topic_messages.values())
        response += f"\n\n📊 <b>Сообщений в памяти:</b> {total_messages}"
        response += f"\n<b>Отслеживаемых топиков:</b> {len(topic_messages)}"

        await message.answer(response, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Error showing config: {e}")
        await message.answer("❌ Ошибка при получении конфигурации")


# === КОМАНДЫ УПРАВЛЕНИЯ AI МОДЕЛЯМИ ===

@dp.message(Command("add_model"))
async def cmd_add_model(message: Message):
    try:
        args = message.text.split()[1:]
        if len(args) < 2:
            await message.answer("❌ Использование: /add_model <название> <модель>\n"
                                 "Пример: /add_model deepseek deepseek/deepseek-chat:free")
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


@dp.message(Command("models"))
async def cmd_models(message: Message):
    try:
        models_text = ai_client.get_available_models()
        await message.answer(models_text)
    except Exception as e:
        logger.error(f"Error getting models: {e}")
        await message.answer("❌ Ошибка при получении списка AI моделей")


# === ТЕСТОВЫЕ КОМАНДЫ ===

@dp.message(Command("test_post"))
async def cmd_test_post(message: Message):
    """Тестовая команда для отправки примеров постов"""
    try:
        args = message.text.split()[1:]
        post_type = args[0] if args else "monday"

        if post_type == "monday":
            await send_test_monday_post(message)
        elif post_type == "friday":
            await send_test_friday_digest(message)
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


async def send_test_monday_post(message: Message):
    """Отправляет тестовый понедельничный пост"""
    try:
        # Собираем текущие сообщения из топиков
        all_messages = []
        for topic_id, messages in topic_messages.items():
            if messages:
                all_messages.extend(messages[-10:])  # Берем последние 10 сообщений

        if not all_messages:
            all_messages = [
                "Нужно доработать авторизацию в проекте",
                "Проблемы с производительностью на мобильных устройствах",
                "Ищем фронтенд разработчика в команду",
                "Обсуждаем дизайн главной страницы"
            ]
            logger.info("Используются тестовые сообщения для демонстрации")

        prompt = f"""
На основе сообщений из топиков сообщества за последние дни, предложи цели и возможные блокеры на текущую неделю.

Сообщения из топиков:
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

        analysis = ai_client.send_request(prompt)

        post_text = f"📅 **Понедельник: Цели и блокеры недели**\n\n{analysis}"

        # Пытаемся отправить в системный топик Conductor
        conductor_topic = db.get_system_topic("conductor")
        if conductor_topic:
            try:
                await bot.send_message(
                    chat_id=MAIN_CHAT_ID,
                    message_thread_id=conductor_topic['topic_id'],
                    text="🔬 **ТЕСТОВЫЙ ПОСТ:**\n" + post_text,
                    parse_mode="Markdown"
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


async def send_test_friday_digest(message: Message):
    """Отправляет тестовый пятничный дайджест"""
    try:
        # Собираем текущие сообщения из топиков
        all_messages = []
        for topic_id, messages in topic_messages.items():
            if messages:
                all_messages.extend(messages)

        if not all_messages:
            all_messages = [
                "Запустили новую фичу авторизации",
                "Обсуждаем дизайн главной страницы",
                "Проблемы с производительностью на мобильных устройствах",
                "Ищем фронтенд разработчика в команду",
                "Провели успешный деплой в продакшен"
            ]
            logger.info("Используются тестовые сообщения для демонстрации")

        prompt = f"""
Создай еженедельный дайджест на основе сообщений из топиков сообщества.

Сообщения из топиков:
{"; ".join(all_messages)}

Структура дайджеста:
👥 Новые участники
💡 Идеи 
🔬 Лаб (next/stop)
🚀 Апдейты проектов
🆘 Помощь 
🛠 Инструмент недели
✅ Решения

Будь кратким, информативным и используй эмодзи для наглядности.
"""

        analysis = ai_client.send_request(prompt)

        post_text = f"📊 **Weekly Digest**\n\n{analysis}"

        # Пытаемся отправить в системный топик Анонсы
        announcements_topic = db.get_system_topic("announcements")
        if announcements_topic:
            try:
                await bot.send_message(
                    chat_id=MAIN_CHAT_ID,
                    message_thread_id=announcements_topic['topic_id'],
                    text="🔬 **ТЕСТОВЫЙ ДАЙДЖЕСТ:**\n" + post_text,
                    parse_mode="Markdown"
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


# === ОБРАБОТЧИКИ СООБЩЕНИЙ ИЗ ТОПИКОВ ===

class SourceTopicsFilter(Filter):
    def __init__(self, db):
        self.db = db

    async def __call__(self, message: Message) -> bool:
        # Проверяем, что сообщение из основного чата
        if str(message.chat.id) != MAIN_CHAT_ID:
            return False

        # Получаем список топиков-источников
        source_topics = self.db.get_source_topics()
        source_topic_ids = [topic['topic_id'] for topic in source_topics]

        # Проверяем, что сообщение из нужного топика
        return (hasattr(message, 'message_thread_id') and
                message.message_thread_id in source_topic_ids)


@dp.message(SourceTopicsFilter(db))
async def handle_source_topic_messages(message: Message):
    """Обрабатывает сообщения из топиков-источников"""
    await process_topic_message(message)


async def process_topic_message(message: Message):
    """Обрабатывает и сохраняет сообщение из топика"""
    try:
        topic_id = message.message_thread_id

        if topic_id not in topic_messages:
            topic_messages[topic_id] = []

        # Сохраняем текст сообщения
        if message.text and not message.text.startswith('/'):
            topic_messages[topic_id].append(message.text)

            # Также сохраняем в базу данных
            message_data = {
                'message_id': message.message_id,
                'chat_id': message.chat.id,
                'topic_id': topic_id,
                'message_text': message.text,
                'thread_id': None,  # Будет установлено при классификации
                'parent_message_id': message.reply_to_message.message_id if message.reply_to_message else None,
                'classification_id': None  # Будет установлено при классификации
            }
            db.save_message(message_data)

            # Ограничиваем количество сообщений в памяти
            if len(topic_messages[topic_id]) > 100:
                topic_messages[topic_id] = topic_messages[topic_id][-50:]

            logger.debug(f"Сообщение сохранено для топика {topic_id}: {message.text[:50]}...")

    except Exception as e:
        logger.error(f"Error processing topic message: {e}")


# === ФУНКЦИИ ДЛЯ АВТОМАТИЧЕСКОГО ПОСТИНГА ===

async def create_monday_post():
    """Создает пост с целями/блокерами на неделю (Пн 10:00)"""
    try:
        conductor_topic = db.get_system_topic("conductor")
        if not conductor_topic:
            logger.error("Топик Conductor не настроен")
            return

        all_messages = []
        for topic_id, messages in topic_messages.items():
            if messages:
                all_messages.extend(messages[-20:])  # Берем последние 20 сообщений

        if not all_messages:
            logger.info("Нет сообщений для анализа по понедельникам")
            return

        prompt = f"""
На основе сообщений из топиков сообщества за последние дни, предложи цели и возможные блокеры на текущую неделю.

Сообщения из топиков:
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

        analysis = ai_client.send_request(prompt)
        post_text = f"📅 **Понедельник: Цели и блокеры недели**\n\n{analysis}"

        await bot.send_message(
            chat_id=MAIN_CHAT_ID,
            message_thread_id=conductor_topic['topic_id'],
            text=post_text,
            parse_mode="Markdown"
        )

        logger.info("Понедельничный пост опубликован")

    except Exception as e:
        logger.error(f"Error creating Monday post: {e}")


async def create_friday_digest():
    """Создает еженедельный дайджест (Пт 19:00)"""
    try:
        announcements_topic = db.get_system_topic("announcements")
        if not announcements_topic:
            logger.error("Топик Анонсы не настроен")
            return

        all_messages = []
        for topic_id, messages in topic_messages.items():
            if messages:
                all_messages.extend(messages)

        if not all_messages:
            logger.info("Нет сообщений для Friday Digest")
            return

        prompt = f"""
Создай еженедельный дайджест на основе сообщений из топиков сообщества.

Сообщения из топиков:
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

        analysis = ai_client.send_request(prompt)
        post_text = f"📊 **Weekly Digest**\n\n{analysis}"

        await bot.send_message(
            chat_id=MAIN_CHAT_ID,
            message_thread_id=announcements_topic['topic_id'],
            text=post_text,
            parse_mode="Markdown"
        )

        # Очищаем сообщения после публикации дайджеста
        for topic_id in topic_messages:
            topic_messages[topic_id] = []

        logger.info("Пятничный дайджест опубликован")

    except Exception as e:
        logger.error(f"Error creating Friday digest: {e}")


# === ПЛАНИРОВЩИК ===

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
                await asyncio.sleep(60)  # Ждем минуту чтобы не запустить дважды

            # Пятница 19:00 - Weekly Digest
            elif weekday == "Friday" and current_time == "19:00":
                await create_friday_digest()
                await asyncio.sleep(60)

            await asyncio.sleep(30)  # Проверяем каждые 30 секунд

        except Exception as e:
            logger.error(f"Error in scheduled posting: {e}")
            await asyncio.sleep(60)


# === ЗАПУСК БОТА ===

async def main():
    logger.info("🚀 Weekly-дайджест бот запускается...")

    # Загружаем топики-источники в память
    source_topics = db.get_source_topics()
    for topic in source_topics:
        topic_messages[topic['topic_id']] = []

    # Показываем конфигурацию при запуске
    conductor_topic = db.get_system_topic("conductor")
    announcements_topic = db.get_system_topic("announcements")

    logger.info(f"Основной чат: {MAIN_CHAT_ID}")
    logger.info(f"Топиков-источников: {len(source_topics)}")
    logger.info(f"Топик Conductor: {conductor_topic['topic_id'] if conductor_topic else 'Не настроен'}")
    logger.info(f"Топик Анонсы: {announcements_topic['topic_id'] if announcements_topic else 'Не настроен'}")

    stats = ai_client.get_stats()
    logger.info(f"AI моделей: {stats['ai_models']}")

    # Запускаем фоновую задачу постинга
    asyncio.create_task(scheduled_posting())

    # Запускаем бота
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
