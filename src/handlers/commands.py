import logging
from aiogram import Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

logger = logging.getLogger(__name__)


async def cmd_start(message: Message):
    """Обработчик команды /start"""
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
/cleanup_messages - очистить старые сообщения из БД

💡 Команды управления топиками должны выполняются внутри нужного топика!
"""
    await message.answer(welcome_text)


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


async def cmd_cleanup_messages(message: Message, db):
    """Очищает старые сообщения из БД"""
    try:
        deleted_count = db.cleanup_old_messages(days=7)
        await message.answer(f"✅ Очистка БД выполнена. Удалено сообщений: {deleted_count}")
    except Exception as e:
        logger.error(f"Error cleaning up messages: {e}")
        await message.answer("❌ Ошибка при очистке БД")


async def cmd_models(message: Message, ai_client):
    """Показывает список AI моделей"""
    try:
        models_text = ai_client.get_available_models()
        await message.answer(models_text)
    except Exception as e:
        logger.error(f"Error getting models: {e}")
        await message.answer("❌ Ошибка при получении списка AI моделей")


async def cmd_add_model(message: Message, ai_client):
    """Добавляет AI модель"""
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


async def cmd_remove_model(message: Message, ai_client):
    """Удаляет AI модель"""
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


def register_command_handlers(dp: Dispatcher, db, ai_client):
    """Регистрирует обработчики команд"""

    # Создаем замыкания для обработчиков, которым нужны дополнительные параметры
    async def wrapped_cleanup_messages(message: Message):
        await cmd_cleanup_messages(message, db)

    async def wrapped_models(message: Message):
        await cmd_models(message, ai_client)

    async def wrapped_add_model(message: Message):
        await cmd_add_model(message, ai_client)

    async def wrapped_remove_model(message: Message):
        await cmd_remove_model(message, ai_client)

    # Регистрируем обработчики
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_get_chat_id, Command("get_chat_id"))
    dp.message.register(wrapped_cleanup_messages, Command("cleanup_messages"))
    dp.message.register(wrapped_models, Command("models"))
    dp.message.register(wrapped_add_model, Command("add_model"))
    dp.message.register(wrapped_remove_model, Command("remove_model"))
