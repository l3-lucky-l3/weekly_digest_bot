import logging
from typing import List, Dict
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

            # Получаем активные треды за последнюю неделю ТОЛЬКО с классификацией 'goal' или 'blocker'
            # Это гарантирует, что пост формируется на основе уже выделенных AI целей и блеров
            active_threads = self.db.get_active_threads_with_messages(days=7)
            relevant_threads = [t for t in active_threads if t['classification_id'] in ['goal', 'blocker']]

            if not relevant_threads:
                logger.info("Нет активных тредов 'goal' или 'blocker' для понедельничного поста")
                # Возможно, стоит создать пост с уведомлением об этом?
                # Пока просто возвращаем False
                return False

            logger.info(f"Найдено {len(relevant_threads)} релевантных тредов для поста.")

            # Используем промпт для анонсов
            prompt = self.db.get_prompt("announce")
            if not prompt:
                logger.error("Промпт для анонсов не настроен")
                return False

            # Подготовка контекста ТОЛЬКО из релевантных тредов
            message_context = self._prepare_monday_context(relevant_threads)
            full_prompt = f"{prompt}\n\nКонтекст для анализа:\n{message_context}"

            post_text = await self.ai_client.send_request_with_retry(full_prompt)

            # Сначала сохраняем сообщение в БД
            message_obj_id = self.db.save_message({
                'message_id': None,
                'topic_id': announce_topic['topic_id'],
                'message_text': post_text,
                'thread_id': None,
                'parent_message_id': None,
                'classification_id': "announce", # <-- Уточняем classification_id для сохраняемого сообщения
                'processed': True
            })

            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"publish_post:{message_obj_id}"),
                 InlineKeyboardButton(text="❌ Редактировать", callback_data=f"edit_post:{message_obj_id}")]
            ])

            await bot.send_message(chat_id=self.admin_chat_id, text=post_text, reply_markup=markup)
            logger.info("Понедельничный пост опубликован")
            return True

        except Exception as e:
            logger.error(f"Error creating Monday post: {e}")
            return False

    def _prepare_monday_context(self, relevant_threads: List[Dict]) -> str:
        """Подготавливает контекст из релевантных (goal/blocker) тредов для понедельничного поста."""
        context_parts = []
        for thread in relevant_threads:
            # Формируем строку с информацией о треде
            thread_info = f"- Тред '{thread['title']}' (Классификация: {thread['classification_id']})"
            # Добавляем ключевые сообщения из треда, если они есть
            if thread['messages']:
                # Берем, например, последние 2-3 сообщения для контекста
                # Можно также использовать первое сообщение треда как основное описание
                key_messages = thread['messages'][-3:]  # Берем последние 3 сообщения
                thread_info += f". Ключевые моменты: {'; '.join(key_messages[:2])}"  # Ограничиваем длину
            context_parts.append(thread_info)
        # Объединяем все в одну строку
        return "\n".join(context_parts)

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

            # Получаем активные треды за неделю для "Разбиения по топикам"
            active_threads = self.db.get_active_threads_with_messages(days=7)

            # Получаем топики-источники
            source_topics = self.db.get_source_topics()

            # Получаем цели и блокеры за неделю
            weekly_goals = self.db.get_threads_by_classification('goal', days=7)
            weekly_blockers = self.db.get_threads_by_classification('blocker', days=7)

            # Получаем последний анонс целей и извлекаем из него цели
            last_announcement = self.db.get_last_announcement()
            last_goals_from_announcement = self._extract_goals_from_announcement(
                last_announcement) if last_announcement else []

            # Используем промпт для дайджестов
            prompt = self.db.get_prompt("digest")
            if not prompt:
                logger.error("Промпт для дайджестов не настроен")
                return False

            # Подготовка контекста для каждого раздела
            topics_context = self._prepare_digest_topics_context(active_threads, source_topics)
            goals_progress_context = self._prepare_goals_progress_context(last_goals_from_announcement, recent_messages)
            blockers_context = self._prepare_digest_blockers_context(weekly_blockers)
            new_goals_context = self._prepare_digest_new_goals_context(weekly_goals)

            # Формируем общий контекст
            message_context = f"""
               --- КОНТЕКСТ ДЛЯ ДАЙДЖЕСТА ---
               # Разбиение по топикам:
               {topics_context}

               # Прошлые цели (из последнего анонса) и их обсуждение за неделю:
               {goals_progress_context}

               # Блокеры недели (новые треды 'blocker'):
               {blockers_context}

               # Новые цели недели (новые треды 'goal'):
               {new_goals_context}

               --- КОНТЕКСТ ДЛЯ ДАЙДЖЕСТА ---
               """

            # Добавляем даты для шаблона
            end_date = datetime.now()
            start_date = end_date - timedelta(days=7)

            full_prompt = prompt.format(
                message_context=message_context,
                start_date=start_date.strftime('%d.%m.%Y'),
                end_date=end_date.strftime('%d.%m.%Y')
            )

            post_text = await self.ai_client.send_request_with_retry(full_prompt)  # Используем retry

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

            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"publish_post:{message_obj_id}"),
                 InlineKeyboardButton(text="❌ Редактировать", callback_data=f"edit_post:{message_obj_id}")]
            ])

            await bot.send_message(chat_id=self.admin_chat_id, text=post_text, reply_markup=markup)
            logger.info("Пятничный дайджест создан с новой структурой")
            return True

        except Exception as e:
            logger.error(f"Error creating Friday digest: {e}")
            return False

    def _prepare_digest_topics_context(self, active_threads: List[Dict], source_topics: List[Dict]) -> str:
        """Подготавливает ЧИСТЫЙ контекст для раздела топиков"""
        if not active_threads:
            return "Нет активных обсуждений"

        topic_names = {t['topic_id']: t['topic_name'] for t in source_topics}
        context_parts = []

        for thread in active_threads:
            topic_id = thread.get('topic_id')
            topic_name = topic_names.get(topic_id, "Общие обсуждения")
            thread_title = thread.get('title', 'Без названия')

            # Берем только релевантные сообщения (не пустые)
            relevant_messages = [msg for msg in thread.get('messages', [])
                                 if msg and msg != "Тред без сообщений...."]

            if relevant_messages:
                # Берем последнее значимое сообщение как контекст
                last_message = relevant_messages[-1][:150] + "..." if len(relevant_messages[-1]) > 150 else \
                relevant_messages[-1]
                context_parts.append(f"{topic_name} | {thread_title}: {last_message}")

        return "\n".join(context_parts) if context_parts else "Нет значимых обсуждений"

    def _prepare_goals_progress_context(self, last_goals: List[str], recent_messages: List[Dict]) -> str:
        """Упрощенный контекст для целей"""
        if not last_goals:
            return "Нет целей из предыдущего анонса"

        context_parts = []
        for goal in last_goals:
            # Простая проверка упоминания
            mentioned = any(goal.lower() in msg.get('message_text', '').lower()
                            for msg in recent_messages)
            status = "обсуждалась" if mentioned else "не упоминалась"
            context_parts.append(f"{goal} - {status}")

        return "\n".join(context_parts)

    def _prepare_digest_blockers_context(self, weekly_blockers: List[Dict]) -> str:
        """Чистый контекст для блокеров"""
        if not weekly_blockers:
            return "Нет новых блокеров"

        context_parts = []
        for blocker in weekly_blockers:
            title = blocker.get('title', 'Без названия')
            messages = blocker.get('messages', [])
            description = messages[0][:100] + "..." if messages else "Описание отсутствует"
            context_parts.append(f"{title}: {description}")

        return "\n".join(context_parts)

    def _prepare_digest_new_goals_context(self, weekly_goals: List[Dict]) -> str:
        """Чистый контекст для новых целей"""
        if not weekly_goals:
            return "Нет новых целей"

        context_parts = []
        for goal in weekly_goals:
            title = goal.get('title', 'Без названия')
            messages = goal.get('messages', [])
            description = messages[0][:100] + "..." if messages else "Описание отсутствует"
            context_parts.append(f"{title}: {description}")

        return "\n".join(context_parts)

    def _extract_goals_from_announcement(self, announcement_text: str) -> List[str]:
        """Извлекает цели из текста последнего анонса (простой парсинг)."""
        # Простой способ: найти строки, начинающиеся с 1., 2., 3. в разделе "🎯 Предлагаемые Цели"
        import re
        # Ищем раздел с целями
        goals_section_match = re.search(r'🎯 Предлагаемые Цели.*?(?=\n\n|$)', announcement_text, re.DOTALL)
        if not goals_section_match:
            return []
        goals_section = goals_section_match.group(0)
        # Ищем цели в формате 1. <b>[Название цели]</b>
        goal_titles = re.findall(r'\d+\.\s*<b>\[([^\]]+)\]</b>', goals_section)
        # Также ищем цели в формате 1. <b>([^<]+)</b> - если название не в квадратных скобках
        goal_titles_alt = re.findall(r'\d+\.\s*<b>([^<]+)</b>', goals_section)
        # Объединяем результаты, убирая дубликаты
        all_titles = list(set(goal_titles + goal_titles_alt))
        return all_titles

    async def create_post(self, post_type, bot):
        """Создает тестовый пост указанного типа"""
        if post_type == "announce":
            return await self.create_monday_post(bot)
        elif post_type == "digest":
            return await self.create_friday_digest(bot)
        else:
            raise ValueError(f"Неизвестный тип поста: {post_type}")
