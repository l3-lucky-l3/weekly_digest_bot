import os
import logging
from aiogram import Dispatcher, F
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

logger = logging.getLogger(__name__)


# Состояния FSM
class PromptStates(StatesGroup):
    waiting_for_prompt = State()
    waiting_for_confirmation = State()


class PostStates(StatesGroup):
    waiting_for_edit = State()


class ParseHTMLStates(StatesGroup):
    waiting_for_html_file = State()


# Глобальные переменные для временного хранения данных
temp_prompt_data = {}
temp_post_data = {}


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

📝 Управление промптами:
/setprompt <announce|digest> - установить промпт для анонсов или дайджестов
/show_prompts - показать текущие промпты
/cancel - отменить настройку промпта

📁 Импорт истории:
/parse_html - импорт истории чата из HTML файла (экспорт Telegram)

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


# AI модели
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


# Промпты
async def cmd_setprompt(message: Message, state: FSMContext, db):
    """Обработчик команды /setprompt"""
    try:
        args = message.text.split()[1:]
        if len(args) < 1:
            await message.answer(
                "❌ Использование: /setprompt <тип>\n"
                "Доступные типы:\n"
                "• <code>announce</code> - промпт для анонсов\n"
                "• <code>digest</code> - промпт для дайджестов\n\n"
                "Пример: /setprompt announce",
                parse_mode="HTML"
            )
            return

        prompt_type = args[0].lower()

        # Проверяем допустимые типы промптов
        valid_types = ['announce', 'digest']
        if prompt_type not in valid_types:
            await message.answer(
                "❌ Неверный тип промпта. Допустимые типы:\n"
                "• <code>announce</code> - промпт для анонсов\n"
                "• <code>digest</code> - промпт для дайджестов",
                parse_mode="HTML"
            )
            return

        # Получаем текущий промпт для отображения
        current_prompt = db.get_prompt(prompt_type)

        prompt_type_names = {
            'announce': 'анонсов',
            'digest': 'дайджестов'
        }

        await message.answer(
            f"✏️ <b>Настройка промпта для {prompt_type_names[prompt_type]}</b>\n\n"
            f"📝 <b>Текущий промпт:</b>\n<code>{current_prompt or 'Не установлен'}</code>\n\n"
            f"📨 <b>Отправьте новый промпт в следующем сообщении:</b>\n"
            f"• Для отмены используйте /cancel",
            parse_mode="HTML"
        )

        # Сохраняем тип промпта в состоянии и временных данных
        await state.update_data(prompt_type=prompt_type)
        await state.set_state(PromptStates.waiting_for_prompt)

    except Exception as e:
        logger.error(f"Error in setprompt command: {e}")
        await message.answer("❌ Ошибка при настройке промпта")


async def handle_prompt_text(message: Message, state: FSMContext):
    """Обработчик текста промпта"""
    try:
        user_data = await state.get_data()
        prompt_type = user_data.get('prompt_type')

        if not prompt_type:
            await message.answer("❌ Ошибка: тип промпта не найден")
            await state.clear()
            return

        # Сохраняем текст промпта во временное хранилище
        global temp_prompt_data
        temp_prompt_data[message.from_user.id] = {
            'type': prompt_type,
            'text': message.text
        }

        prompt_type_names = {
            'announce': 'анонсов',
            'digest': 'дайджестов'
        }

        # Создаем клавиатуру с кнопками подтверждения
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Да", callback_data="prompt_confirm_yes"),
                    InlineKeyboardButton(text="❌ Нет", callback_data="prompt_confirm_no")
                ]
            ]
        )

        await message.answer(
            f"📋 <b>Подтвердите новый промпт для {prompt_type_names[prompt_type]}:</b>\n\n"
            f"<code>{message.text}</code>\n\n"
            f"<b>Сохранить этот промпт?</b>",
            parse_mode="HTML",
            reply_markup=markup
        )

        await state.set_state(PromptStates.waiting_for_confirmation)

    except Exception as e:
        logger.error(f"Error handling prompt text: {e}")
        await message.answer("❌ Ошибка при обработке промпта")
        await state.clear()


async def handle_prompt_confirmation(callback: CallbackQuery, state: FSMContext, db):
    """Обработчик подтверждения промпта через inline кнопки"""
    try:
        global temp_prompt_data

        user_id = callback.from_user.id
        prompt_data = temp_prompt_data.get(user_id)

        if not prompt_data:
            await callback.message.edit_text("❌ Данные промпта не найдены. Начните заново.")
            await state.clear()
            return

        prompt_type = prompt_data['type']
        prompt_text = prompt_data['text']

        prompt_type_names = {
            'announce': 'анонсов',
            'digest': 'дайджестов'
        }

        if callback.data == "prompt_confirm_yes":
            # Сохраняем промпт в базу данных
            if db.update_prompt(prompt_type, prompt_text):
                await callback.message.edit_text(
                    f"✅ <b>Промпт для {prompt_type_names[prompt_type]} успешно обновлен!</b>",
                    parse_mode="HTML"
                )
                logger.info(f"Prompt updated for type: {prompt_type}")
            else:
                await callback.message.edit_text("❌ Ошибка при сохранении промпта в базу данных")
        else:
            await callback.message.edit_text("❌ Изменения отменены")

        # Очищаем временные данные и состояние
        if user_id in temp_prompt_data:
            del temp_prompt_data[user_id]
        await state.clear()

    except Exception as e:
        logger.error(f"Error handling prompt confirmation: {e}")
        await callback.message.edit_text("❌ Ошибка при подтверждении")
        await state.clear()


async def cmd_cancel_prompt(message: Message, state: FSMContext):
    """Отмена настройки промпта"""
    try:
        global temp_prompt_data

        user_id = message.from_user.id
        if user_id in temp_prompt_data:
            del temp_prompt_data[user_id]

        await message.answer("❌ Настройка промпта отменена")
        await state.clear()

    except Exception as e:
        logger.error(f"Error canceling prompt: {e}")
        await state.clear()


async def cmd_show_prompts(message: Message, db):
    """Показывает текущие промпты"""
    try:
        announce_prompt = db.get_prompt('announce')
        digest_prompt = db.get_prompt('digest')

        response = "📝 <b>Текущие промпты:</b>\n\n"

        response += "🔔 <b>Промпт для анонсов:</b>\n"
        if announce_prompt:
            response += f"<code>{announce_prompt}</code>\n"
        else:
            response += "<i>Не установлен</i>\n"

        response += "\n📊 <b>Промпт для дайджестов:</b>\n"
        if digest_prompt:
            response += f"<code>{digest_prompt}</code>\n"
        else:
            response += "<i>Не установлен</i>\n"

        response += "\n⚙️ <b>Команды для изменения:</b>\n"
        response += "<code>/setprompt announce</code> - изменить промпт анонсов\n"
        response += "<code>/setprompt digest</code> - изменить промпт дайджестов"

        await message.answer(response, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Error showing prompts: {e}")
        await message.answer("❌ Ошибка при получении промптов")


# Тестовые посты
async def cmd_test_post(message: Message, bot, posting_service):
    """Тестовая команда для отправки примеров постов"""
    try:
        args = message.text.split()[1:]
        post_type = args[0] if args else "monday"

        if post_type not in ["monday", "friday"]:
            await message.answer(
                "❌ Использование: /test_post <тип>\n"
                "Типы:\n"
                "• monday - тест понедельничного поста\n"
                "• friday - тест пятничного дайджеста\n"
                "Пример: /test_post monday"
            )

        success = await posting_service.create_test_post(post_type, bot)

        if success:
            await message.answer(f"✅ Тестовый {post_type} пост успешно создан")
        else:
            await message.answer(f"❌ Ошибка при создании тестового {post_type} поста")

    except Exception as e:
        logger.error(f"Error in test_post command: {e}")
        await message.answer("❌ Ошибка при создании тестового поста")


# Посты
async def handle_post_confirmation(callback: CallbackQuery, state: FSMContext, db, bot, posting_service):
    """Обработчик кнопок публикации/редактирования поста"""
    try:
        action, message_obj_id_str = callback.data.split(":")
        message_obj_id = int(message_obj_id_str)
        message_data = db.get_message_by_id(message_obj_id)

        if not message_data:
            await callback.answer("❌ Сообщение не найдено в базе данных")
            return

        if action == "publish_post":
            # Публикуем пост в основной чат
            try:
                message_info = await bot.send_message(
                    chat_id=posting_service.main_chat_id,
                    message_thread_id=message_data['topic_id'],
                    text=message_data['message_text'],
                    parse_mode="HTML"
                )
                db.update_telegram_message_id(message_obj_id, message_info.message_id)

                await callback.message.edit_text(
                    f"✅ Пост опубликован!\n\n{message_data['message_text']}",
                    parse_mode="HTML"
                )
                logger.info(f"Пост {message_obj_id} опубликован в основной чат")

            except Exception as e:
                await callback.answer(f"❌ Ошибка публикации: {e}")

        elif action == "edit_post":
            # Запрашиваем новый текст для редактирования
            temp_post_data[callback.from_user.id] = {
                'message_obj_id': message_obj_id,
                'original_text': message_data['message_text']
            }

            markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Отправить текущий текст", callback_data=f"publish_post:{message_obj_id}")]
                ]
            )

            await callback.message.edit_text(
                f"✏️ Редактирование поста:\n\n\n"
                f"Текущий текст:\n\n`{message_data['message_text']}\n\n\n"
                f"📝 Отправьте новый текст поста:",
                reply_markup=markup
            )

            await state.set_state(PostStates.waiting_for_edit)

    except Exception as e:
        logger.error(f"Error handling post confirmation: {e}")
        await callback.answer("❌ Ошибка при обработке")


async def handle_post_edit(message: Message, state: FSMContext, db):
    """Обработчик нового текста для редактирования поста"""
    try:
        user_id = message.from_user.id
        post_data = temp_post_data.get(user_id)

        if not post_data:
            await message.answer("❌ Данные поста не найдены")
            await state.clear()
            return

        message_obj_id = post_data['message_obj_id']

        # Обновляем сообщение в базе данных
        updated = db.update_message_text(message_obj_id, message.text)

        if updated:
            # Снова показываем кнопки публикации
            markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"publish_post:{message_obj_id}"),
                        InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_post:{message_obj_id}")
                    ]
                ]
            )

            await message.answer(
                f"📝 <b>Пост обновлен:</b>\n\n"
                f"{message.text}\n\n"
                f"<b>Выберите действие:</b>",
                reply_markup=markup
            )

            # Сохраняем ID нового сообщения для дальнейших действий
            new_message_id = message.message_id
            temp_post_data[user_id]['last_message_id'] = new_message_id

            await state.set_state(PostStates.waiting_for_edit)

            logger.info(f"Пост {message_obj_id} обновлен")
        else:
            await message.answer("❌ Ошибка при обновлении поста в базе данных")

    except Exception as e:
        logger.error(f"Error handling post edit: {e}")
        await message.answer("❌ Ошибка при редактировании поста")
    finally:
        await state.clear()


async def handle_cancel_edit(callback: CallbackQuery, state: FSMContext):
    """Отмена редактирования"""
    try:
        user_id = callback.from_user.id
        if user_id in temp_post_data:
            del temp_post_data[user_id]

        await callback.message.edit_text("❌ Редактирование отменено")
        await state.clear()

    except Exception as e:
        logger.error(f"Error canceling edit: {e}")
        await state.clear()


# Парсинг истории чата
async def cmd_parse_html(message: Message, state: FSMContext, html_parser, bot):
    """Обработчик команды /parse_html - запускает процесс парсинга истории чата"""
    await message.answer(
        "📁 <b>Парсинг истории чата из HTML файла</b>\n\n"
        "Отправьте мне файл <code>messages.html</code> (экспорт из Telegram)\n\n"
        "⚠️ <i>Файл должен быть в формате экспорта Telegram</i>\n"
        "❌ Для отмены используйте /cancel",
        parse_mode="HTML"
    )
    await state.set_state(ParseHTMLStates.waiting_for_html_file)


async def handle_html_file(message: Message, state: FSMContext, html_parser, bot):
    """Обработчик получения HTML файла"""
    try:
        if not message.document:
            await message.answer("❌ Пожалуйста, отправьте файл messages.html")
            return

        if not message.document.file_name.endswith('.html'):
            await message.answer("❌ Файл должен быть в формате HTML")
            return

        # Скачиваем файл
        file_info = await bot.get_file(message.document.file_id)
        downloaded_file = await bot.download_file(file_info.file_path)

        # Сохраняем временный файл
        temp_file_path = f"temp_messages_{message.from_user.id}.html"
        with open(temp_file_path, 'wb') as f:
            f.write(downloaded_file.read())

        await message.answer("⏳ <b>Начинаю парсинг файла...</b>", parse_mode="HTML")

        # Парсим HTML файл
        result = await html_parser.parse_html_file(temp_file_path)

        # Удаляем временный файл
        os.remove(temp_file_path)

        if result['success']:
            await message.answer(
                f"✅ <b>Парсинг завершен успешно!</b>\n\n"
                f"📊 <b>Статистика:</b>\n"
                f"• Сообщений обработано: {result['total_messages']}\n"
                f"• Сообщений сохранено: {result['saved_messages']}\n"
                f"• Топиков найдено: {result['topics_found']}\n"
                f"• Время обработки: {result['processing_time']:.2f} сек.\n\n"
                f"💾 <b>Данные сохранены в базу</b>",
                parse_mode="HTML"
            )
        else:
            await message.answer(
                f"❌ <b>Ошибка при парсинге:</b>\n{result['error']}",
                parse_mode="HTML"
            )

        await state.clear()

    except Exception as e:
        logger.error(f"Error processing HTML file: {e}")
        await message.answer(f"❌ <b>Ошибка при обработке файла:</b>\n{str(e)}", parse_mode="HTML")
        await state.clear()


async def cmd_cancel_parse(message: Message, state: FSMContext):
    """Отмена парсинга HTML"""
    await message.answer("❌ Парсинг отменен")
    await state.clear()


def register_command_handlers(dp: Dispatcher, db, bot, ai_client, posting_service, html_parser):
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

    async def wrapped_setprompt(message: Message, state: FSMContext):
        await cmd_setprompt(message, state, db)

    async def wrapped_handle_prompt_text(message: Message, state: FSMContext):
        await handle_prompt_text(message, state)

    async def wrapped_handle_confirmation(callback: CallbackQuery, state: FSMContext):
        await handle_prompt_confirmation(callback, state, db)

    async def wrapped_show_prompts(message: Message):
        await cmd_show_prompts(message, db)

    async def wrapped_test_post(message: Message):
        await cmd_test_post(message, bot, posting_service)

    async def wrapped_handle_post_confirmation(callback: CallbackQuery, state: FSMContext):
        await handle_post_confirmation(callback, state, db, bot, posting_service)

    async def wrapped_handle_post_edit(message: Message, state: FSMContext):
        await handle_post_edit(message, state, db)

    async def wrapped_handle_cancel_edit(callback: CallbackQuery, state: FSMContext):
        await handle_cancel_edit(callback, state)

    async def wrapped_parse_html(message: Message, state: FSMContext):
        await cmd_parse_html(message, state, html_parser, bot)

    async def wrapped_handle_html_file(message: Message, state: FSMContext):
        await handle_html_file(message, state, html_parser, bot)

    # Регистрируем обработчики команд
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_get_chat_id, Command("get_chat_id"))
    dp.message.register(wrapped_cleanup_messages, Command("cleanup_messages"))

    dp.message.register(wrapped_models, Command("models"))
    dp.message.register(wrapped_add_model, Command("add_model"))
    dp.message.register(wrapped_remove_model, Command("remove_model"))

    dp.message.register(wrapped_setprompt, Command("setprompt"))
    dp.message.register(wrapped_show_prompts, Command("show_prompts"))
    dp.message.register(cmd_cancel_prompt, Command("cancel"))
    dp.message.register(
        wrapped_handle_prompt_text,
        StateFilter(PromptStates.waiting_for_prompt)
    )
    dp.callback_query.register(
        wrapped_handle_confirmation,
        StateFilter(PromptStates.waiting_for_confirmation),
        F.data.in_(["prompt_confirm_yes", "prompt_confirm_no"])
    )

    dp.message.register(wrapped_test_post, Command("test_post"))

    dp.callback_query.register(
        wrapped_handle_post_confirmation,
        F.data.regexp(r'^(publish_post|edit_post):\d+$')
    )
    dp.callback_query.register(
        wrapped_handle_cancel_edit,
        F.data == "cancel_edit"
    )
    dp.message.register(
        wrapped_handle_post_edit,
        StateFilter(PostStates.waiting_for_edit)
    )

    dp.message.register(wrapped_parse_html, Command("parse_html"))
    dp.message.register(
        wrapped_handle_html_file,
        ParseHTMLStates.waiting_for_html_file
    )
    dp.message.register(
        cmd_cancel_parse,
        Command("cancel"),
        ParseHTMLStates.waiting_for_html_file
    )
