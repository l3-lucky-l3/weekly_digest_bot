import logging
from datetime import datetime, timedelta
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


logger = logging.getLogger(__name__)


class PostingService:
    def __init__(self, db, ai_client, main_chat_id, admin_chat_id):
        self.db = db
        self.ai_client = ai_client
        self.main_chat_id = main_chat_id
        self.admin_chat_id = admin_chat_id

    async def create_monday_post(self, bot):
        """Создает пост с целями/блокерами на неделю (Пн 10:00)"""
        try:
            announce_topic = self.db.get_system_topic("announce")
            if not announce_topic:
                logger.error("Топик announce не настроен")
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
                'topic_id': announce_topic['topic_id'],
                'message_text': post_text,
                'thread_id': None,
                'parent_message_id': None,
                'classification_id': "announce",
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
            digest_topic = self.db.get_system_topic("digest")
            if not digest_topic:
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

            # Добавляем контекст сообщений с новой структурой
            message_context = self._prepare_digest_context(recent_messages)

            # Добавляем даты для шаблона
            end_date = datetime.now()
            start_date = end_date - timedelta(days=7)
            date_range = f"{start_date.strftime('%d.%m.%Y')} – {end_date.strftime('%d.%m.%Y')}"

            full_prompt = f"{prompt}\n\nПериод: {date_range}\n\nКонтекст:\n{message_context}"

            post_text = await self.ai_client.send_request(full_prompt)

            # Сначала сохраняем сообщение в БД
            message_obj_id = self.db.save_message({
                'message_id': None,
                'topic_id': digest_topic['topic_id'],
                'message_text': post_text,
                'thread_id': None,
                'parent_message_id': None,
                'classification_id': "digest",
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

            logger.info("Пятничный дайджест создан с новой структурой")
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
        """Подготавливает контекст для пятничного дайджеста с новой структурой"""

        # 1. Получаем топики-источники и их сообщения
        source_topics = self.db.get_source_topics()
        topics_context = {}

        for topic in source_topics:
            topic_messages = [msg for msg in recent_messages
                              if msg.get('topic_id') == topic['topic_id']]
            if topic_messages:
                topics_context[topic['topic_name'] or f"Топик {topic['topic_id']}"] = [
                    msg['message_text'] for msg in topic_messages[:10]  # Берем до 10 сообщений на топик
                ]

        # 2. Получаем последний анонс целей
        last_announcement = self.db.get_last_announcement()

        # 3. Получаем цели и блокеры за неделю
        weekly_goals = [msg for msg in recent_messages
                        if msg.get('classification_id') == 'goal']
        weekly_blockers = [msg for msg in recent_messages
                           if msg.get('classification_id') == 'blocker']

        context_parts = []

        # Контекст по топикам
        context_parts.append("=== ОБСУЖДЕНИЯ ПО ТОПИКАМ ===")
        for topic_name, messages in topics_context.items():
            context_parts.append(f"Топик: {topic_name}")
            context_parts.extend(messages[:3])  # Берем 3 сообщения для контекста
            context_parts.append("---")

        # Контекст прошлого анонса
        if last_announcement:
            context_parts.append("=== ПРОШЛЫЙ АНОНС ЦЕЛЕЙ ===")
            context_parts.append(last_announcement)

        # Контекст новых целей
        if weekly_goals:
            context_parts.append("=== НОВЫЕ ЦЕЛИ ЗА НЕДЕЛЮ ===")
            for goal in weekly_goals[:5]:
                context_parts.append(f"Цель: {goal['message_text'][:100]}...")

        # Контекст блокеров
        if weekly_blockers:
            context_parts.append("=== БЛОКЕРЫ ЗА НЕДЕЛЮ ===")
            for blocker in weekly_blockers[:5]:
                context_parts.append(f"Блокер: {blocker['message_text'][:100]}...")

        return "\n".join(context_parts)

    async def create_test_post(self, post_type, bot):
        """Создает тестовый пост указанного типа"""
        if post_type == "announce":
            return await self.create_monday_post(bot)
        elif post_type == "digest":
            return await self.create_friday_digest(bot)
        else:
            raise ValueError(f"Неизвестный тип поста: {post_type}")
