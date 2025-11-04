import logging
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


logger = logging.getLogger(__name__)


class PostingService:
    def __init__(self, db, ai_client, main_chat_id, admin_chat_id):
        self.db = db
        self.ai_client = ai_client
        # TODO del?
        self.main_chat_id = main_chat_id
        self.admin_chat_id = admin_chat_id

    async def create_monday_post(self, bot):
        """Создает пост с целями/блокерами на неделю (Пн 10:00)"""
        try:
            conductor_topic = self.db.get_system_topic("conductor")
            if not conductor_topic:
                logger.error("Топик Conductor не настроен")
                return False

            # Получаем активные треды за последнюю неделю
            active_threads = self.db.get_active_threads_with_messages(days=7)

            if not active_threads:
                logger.info("Нет активных тредов для понедельничного поста")
                return False

            # Используем промпт для анонсов
            prompt = self.db.get_prompt("announce")
            if not prompt:
                logger.error("Промпт для анонсов не настроен")
                return False

            # Добавляем контекст сообщений
            message_context = self._prepare_message_context(active_threads)
            full_prompt = f"{prompt}\n\n{message_context}"

            post_text = await self.ai_client.send_request(full_prompt)

            # Сначала сохраняем сообщение в БД
            message_obj_id = self.db.save_message({
                'message_id': None,
                'topic_id': conductor_topic['topic_id'],
                'message_text': post_text,
                'thread_id': None,
                'parent_message_id': None,
                'classification_id': "conductor",
                'processed': True
            })

            markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"publish_post:{message_obj_id}"),
                        InlineKeyboardButton(text="❌ Редактировать", callback_data=f"edit_post:{message_obj_id}")
                    ]
                ]
            )

            await bot.send_message(
                chat_id=self.admin_chat_id,
                text=post_text,
                reply_markup=markup
            )

            logger.info("Понедельничный пост опубликован")
            return True

        except Exception as e:
            logger.error(f"Error creating Monday post: {e}")
            return False

    async def create_friday_digest(self, bot):
        """Создает еженедельный дайджест (Пт 19:00)"""
        try:
            announcements_topic = self.db.get_system_topic("announcements")
            if not announcements_topic:
                logger.error("Топик Анонсы не настроен")
                return False

            # Получаем сообщения из БД за последнюю неделю
            recent_messages = self.db.get_messages_for_period(days=7)

            if not recent_messages:
                logger.info("Нет сообщений в БД для Friday Digest")
                return False

            # Используем промпт для дайджестов
            prompt = self.db.get_prompt("digest")
            if not prompt:
                logger.error("Промпт для дайджестов не настроен")
                return False

            # Добавляем контекст сообщений
            message_context = self._prepare_digest_context(recent_messages)
            full_prompt = f"{prompt}\n\n{message_context}"

            post_text = await self.ai_client.send_request(full_prompt)

            # TODO
            await bot.send_message(
                chat_id=self.admin_chat_id,
                message_thread_id=announcements_topic['topic_id'],
                text=post_text,
                parse_mode="HTML"
            )

            logger.info("Пятничный дайджест опубликован")
            return True

        except Exception as e:
            logger.error(f"Error creating Friday digest: {e}")
            return False

    def _prepare_message_context(self, active_threads):
        """Подготавливает контекст сообщений для понедельничного поста"""
        context_parts = []

        for thread in active_threads:
            if thread['messages']:
                thread_context = f"Тред '{thread['title']}' ({thread['classification_id']}): "
                thread_context += "; ".join(thread['messages'][:5])  # Берем первые 5 сообщений
                context_parts.append(thread_context)

        return "Активные обсуждения:\n" + "\n".join(context_parts)

    def _prepare_digest_context(self, recent_messages):
        """Подготавливает контекст для пятничного дайджеста"""
        message_texts = [msg['message_text'] for msg in recent_messages if msg['message_text']]
        return "Сообщения из топиков:\n" + "\n".join(message_texts[:20])  # Ограничиваем количество

    async def create_test_post(self, post_type, bot):
        """Создает тестовый пост указанного типа"""
        if post_type == "monday":
            return await self.create_monday_post(bot)
        elif post_type == "friday":
            return await self.create_friday_digest(bot)
        else:
            raise ValueError(f"Неизвестный тип поста: {post_type}")
