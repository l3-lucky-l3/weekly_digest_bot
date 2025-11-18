import logging
import asyncio
import json
import re
from typing import List, Dict

logger = logging.getLogger(__name__)


class ClassificationService:
    def __init__(self, db, ai_client, batch_size: int = 5):
        self.db = db
        self.ai_client = ai_client
        self.batch_size = batch_size

    async def process_unprocessed_messages(self):
        """Обрабатывает необработанные сообщения с пакетной классификацией, сгруппированной по топикам"""
        try:
            unprocessed_messages = self.db.get_unprocessed_messages()
            if not unprocessed_messages:
                logger.info("Нет необработанных сообщений")
                return 0

            # Группируем необработанные сообщения по топику
            messages_by_topic = {}
            for msg in unprocessed_messages:
                topic_id = msg['topic_id']
                if topic_id not in messages_by_topic:
                    messages_by_topic[topic_id] = []
                messages_by_topic[topic_id].append(msg)

            total_processed = 0
            logger.info(f"Найдено {len(unprocessed_messages)} необработанных сообщений в {len(messages_by_topic)} топиках")

            for topic_id, topic_messages in messages_by_topic.items():
                logger.info(f"Обработка топика {topic_id}: {len(topic_messages)} сообщений")
                # Получаем активные треды ТОЛЬКО для этого топика
                active_threads = self.db.get_active_threads_with_messages_for_topic(topic_id, days=7)
                logger.info(f"Найдено {len(active_threads)} активных тредов в топике {topic_id}")

                # Разбиваем сообщения топика на пакеты
                batches = [topic_messages[i:i + self.batch_size]
                           for i in range(0, len(topic_messages), self.batch_size)]

                topic_processed = 0
                for batch_num, batch in enumerate(batches, 1):
                    logger.info(f"Топик {topic_id}: Обработка пакета {batch_num}/{len(batches)} ({len(batch)} сообщений)")
                    processed_in_batch = await self.process_batch(batch, active_threads)
                    topic_processed += processed_in_batch

                    # Добавляем паузу между пакетами
                    if batch_num < len(batches):
                        await asyncio.sleep(0.1)  # 100ms пауза

                total_processed += topic_processed
                logger.info(f"Обработка топика {topic_id} завершена. Обработано: {topic_processed}")

            logger.info(f"Обработка ВСЕХ топиков завершена. Всего обработано: {total_processed}")
            return total_processed

        except Exception as e:
            logger.error(f"Ошибка обработки необработанных сообщений: {e}")
            return 0

    # Остальные методы остаются без изменений, так как они уже принимают batch и active_threads
    # и работают с ними в контексте текущего топика (через batch и active_threads, полученные выше).
    # ... (остальные методы как в предыдущем обновленном коде, без изменений) ...
    async def process_batch(self, messages_batch: List[Dict], active_threads: List[Dict]) -> int:
        """Обрабатывает пакет сообщений"""
        try:
            processed_count = 0

            # Шаг 1: Обработка реплаев (не требует AI)
            remaining_messages = await self._batch_step1_replies(messages_batch)
            processed_count += (len(messages_batch) - len(remaining_messages))

            if not remaining_messages:
                return processed_count

            # Шаг 2: Пакетный семантический слинг
            sling_processed, remaining_after_sling = await self._batch_step2_semantic_sling(remaining_messages,
                                                                                            active_threads)
            processed_count += sling_processed

            if not remaining_after_sling:
                return processed_count

            # Шаг 3: Пакетная классификация новых сущностей
            classification_processed = await self._batch_step3_new_entities(remaining_after_sling)
            processed_count += classification_processed

            return processed_count

        except Exception as e:
            logger.error(f"Ошибка обработки пакета: {e}")
            # Резервный вариант: индивидуальная обработка
            return await self._fallback_individual_processing(messages_batch, active_threads)

    async def _batch_step1_replies(self, messages_batch: List[Dict]) -> List[Dict]:
        """Пакетная обработка реплаев"""
        remaining_messages = []

        for message in messages_batch:
            if await self._step1_check_reply(message):
                continue  # Сообщение обработано
            remaining_messages.append(message)

        logger.debug(f"Шаг 1: обработано реплаев: {len(messages_batch) - len(remaining_messages)}")
        return remaining_messages

    async def _batch_step2_semantic_sling(self, messages_batch: List[Dict], active_threads: List[Dict]) -> tuple[
        int, List[Dict]]:
        """Пакетный семантический слинг"""
        if not messages_batch or not active_threads:
            logger.info("Пропуск слинга: нет сообщений или активных тредов.")
            return 0, messages_batch

        try:
            # Создаем пакетный запрос для всех сообщений
            batch_prompt = self._create_batch_sling_prompt(messages_batch, active_threads)
            response = await self.ai_client.send_request_with_retry(batch_prompt)

            # Парсим ответ и применяем результаты
            sling_results = self._parse_batch_sling_response(response)

            processed_count = 0
            remaining_messages = []

            for i, message in enumerate(messages_batch):
                if i < len(sling_results) and sling_results[i]['related'] and sling_results[i]['thread_id']:
                    # Получаем информацию о треде, к которому привязываем
                    thread = self.db.get_thread_by_id(sling_results[i]['thread_id'])
                    if thread:
                        # Привязываем сообщение к найденному треду, используя его классификацию
                        # Классификация сообщения в треде наследуется от треда
                        self.db.update_message_thread(
                            message['message_id'],
                            sling_results[i]['thread_id'],
                            thread['classification_id'] # <-- Классификация наследуется от треда
                        )
                        processed_count += 1
                        logger.debug(
                            f"Пакетный слинг: сообщение {message['message_id']} → тред {sling_results[i]['thread_id']} (классификация: {thread['classification_id']})")
                    else:
                        logger.warning(f"Тред {sling_results[i]['thread_id']} не найден в БД при слинге.")
                        remaining_messages.append(message)
                else:
                    # Если AI не нашел связи, оставляем сообщение для дальнейшей классификации
                    remaining_messages.append(message)

            logger.debug(f"Шаг 2: пакетный слинг обработал: {processed_count}")
            return processed_count, remaining_messages

        except Exception as e:
            logger.error(f"Ошибка пакетного слинга: {e}")
            return 0, messages_batch

    async def _batch_step3_new_entities(self, messages_batch: List[Dict]) -> int:
        """Пакетная классификация новых сущностей"""
        if not messages_batch:
            return 0

        try:
            # Создаем пакетный запрос для классификации
            batch_prompt = self._create_batch_classification_prompt(messages_batch)
            response = await self.ai_client.send_request_with_retry(batch_prompt)

            # Парсим результаты
            classification_results = self._parse_batch_classification_response(response)
            processed_count = 0

            for i, message in enumerate(messages_batch):
                if i < len(classification_results):
                    result = classification_results[i]
                    # Применяем результат классификации, который может создать новый тред
                    if await self._apply_classification_result(message, result):
                        processed_count += 1
                else:
                    # Если не хватило результатов, помечаем как 'other'
                    self.db.update_message_thread(message['message_id'], None, 'other')
                    processed_count += 1
                    logger.warning(f"Нет результата классификации для сообщения {message['message_id']}, помечено как 'other'.")

            logger.debug(f"Шаг 3: пакетная классификация обработала: {processed_count}")
            return processed_count

        except Exception as e:
            logger.error(f"Ошибка пакетной классификации: {e}")
            # Резервный вариант: индивидуальная обработка
            return await self._fallback_individual_classification(messages_batch)

    def _create_batch_sling_prompt(self, messages_batch: List[Dict], active_threads: List[Dict]) -> str:
        """Создает промпт для пакетного семантического слинга"""
        # Форматируем треды для контекста, теперь включая *все* сообщения треда
        threads_context = ""
        for i, thread in enumerate(active_threads[:15]):  # Ограничиваем количество тредов для контекста
            all_thread_messages = thread.get('messages', []) # Получаем все сообщения треда
            # Формируем краткий превью темы и содержания
            messages_preview = " ".join(all_thread_messages) if all_thread_messages else "Тред без сообщений."
            # Ограничиваем длину превью, если оно слишком длинное
            messages_preview = messages_preview[:300] + "..." if len(messages_preview) > 300 else messages_preview

            threads_context += f"{i + 1}. Тред #{thread['thread_id']} (Классификация: {thread['classification_id']}):\n"
            threads_context += f"   Заголовок: {thread['title']}\n"
            threads_context += f"   Контекст (все сообщения): {messages_preview}\n\n"

        # Форматируем сообщения для классификации
        messages_context = ""
        for i, message in enumerate(messages_batch):
            messages_context += f"{i + 1}. Сообщение ID {message['message_id']}:\n   \"{message['message_text'][:300]}\"\n\n"

        prompt = f"""
Ты - ассистент для семантического связывания сообщений в IT-сообществе.
Твоя задача - определить, относится ли каждое из следующих сообщений по смыслу к одному из существующих тредов.

СУЩЕСТВУЮЩИЕ ТРЕДЫ:
{threads_context}

СООБЩЕНИЯ ДЛЯ АНАЛИЗА:
{messages_context}

ПРОЦЕСС АНАЛИЗА:
1. Внимательно проанализируй КАЖДОЕ сообщение из 'СООБЩЕНИЯ ДЛЯ АНАЛИЗА'.
2. Сравни его с темой и содержанием КАЖДОГО треда из 'СУЩЕСТВУЮЩИЕ ТРЕДЫ'.
3. Сообщение СВЯЗАНО с тредом, если:
   - Оно логически продолжает обсуждение в треде.
   - Оно напрямую отвечает на вопросы или касается темы, обсуждаемой в треде.
   - Оно касается проекта, идеи или проблемы, которая была начата или описана в треде.
   - Оно упоминает сущности (люди, проекты, задачи), обсуждаемые в треде, в контексте этого обсуждения.
4. Сообщение НЕ СВЯЗАНО с тредом, если:
   - Оно касается новой темы, не упомянутой в треде.
   - Оно упоминает похожие слова, но в другом контексте, не относящемся к обсуждению треда.
   - Оно описывает ситуацию, не имеющую отношения к теме или участникам обсуждения треда.

Примеры (для понимания):
- Тред о "боте для ПТСР". Сообщение: "Проблема с открытием xlsx". -> НЕ СВЯЗАНО (другая тема).
- Тред о "боте для ПТСР". Сообщение: "Нужно добавить функцию А в бота". -> СВЯЗАНО (продолжение темы).

ВАЖНО: Сообщение должно быть напрямую связано с темой и обсуждением внутри треда, а не просто упоминать похожие слова в другом контексте.

Верни ответ ТОЛЬКО в формате JSON без дополнительного текста:

{{
    "results": [
        {{
            "message_id": {messages_batch[0]['message_id']},
            "related": true,
            "thread_id": 123,
            "confidence": 0.85
        }},
        {{
            "message_id": {messages_batch[1]['message_id']}, 
            "related": false,
            "thread_id": null,
            "confidence": 0.1
        }}
    ]
}}

Важно: верни результат для КАЖДОГО сообщения в том же порядке!
"""
        return prompt

    def _create_batch_classification_prompt(self, messages_batch: List[Dict]) -> str:
        """Создает промпт для пакетной классификации"""

        messages_context = ""
        for i, message in enumerate(messages_batch):
            messages_context += f"{i + 1}. \"{message['message_text']}\"\n"

        prompt = f"""
Ты - классификатор сообщений для IT-сообщества. 
Проанализируй сообщения и определи их типы.

ОПРЕДЕЛЕНИЯ:
- "goal" - новая идея, проект, исследование или задача для выполнения, которая может быть отслеживаемой.
- "blocker" - проблема или обстоятельство, которое мешает работе над текущими целями или проектами, или которое нужно решить для прогресса. Это должна быть конкретная проблема, влияющая на продвижение вперед.
- "other" - обычное сообщение, комментарий, факт, не требующее отдельного отслеживания как goal или blocker.

СООБЩЕНИЯ ДЛЯ КЛАССИФИКАЦИИ:
{messages_context}

ПРОЦЕСС КЛАССИФИКАЦИИ:
1. Проанализируй КАЖДОЕ сообщение отдельно.
2. Определи тип: goal, blocker или other. Строго следуй определениям.
3. Для goal/blocker придумай краткое, информативное название (3-5 слов), отражающее суть.
4. Оцени уверенность от 0 до 1. Уверенность должна отражать, насколько четко сообщение соответствует определению типа.

Примеры (для понимания):
- "Сделать MVP бота" -> "goal", "Сделать MVP".
- "Проблема с xlsx" -> "blocker", если это мешает текущему проекту; иначе "other".
- "Как дела?" -> "other".

Верни ответ ТОЛЬКО в формате JSON без дополнительного текста:

{{
    "results": [
        {{
            "message_index": 0,
            "classification": "goal",
            "confidence": 0.8,
            "title": "Разработка нового модуля"
        }},
        {{
            "message_index": 1, 
            "classification": "other",
            "confidence": 0.9,
            "title": null
        }}
    ]
}}

Важно: верни результат для КАЖДОГО сообщения в том же порядке! Индексы должны начинаться с 0.
"""
        return prompt

    def _parse_batch_sling_response(self, response: str) -> List[Dict]:
        """Парсит ответ пакетного слинга"""
        try:
            # Очищаем ответ от возможных лишних символов
            cleaned_response = response.strip()
            if cleaned_response.startswith('```json'):
                cleaned_response = cleaned_response[7:]
            if cleaned_response.endswith('```'):
                cleaned_response = cleaned_response[:-3]
            cleaned_response = cleaned_response.strip()

            # Парсим JSON
            data = json.loads(cleaned_response)
            results = data.get('results', [])

            # Валидируем результаты
            validated_results = []
            for result in results:
                if all(key in result for key in ['message_id', 'related', 'thread_id', 'confidence']):
                    validated_results.append({
                        'message_id': result['message_id'],
                        'related': bool(result['related']),
                        'thread_id': result['thread_id'] if result['thread_id'] else None,
                        'confidence': float(result['confidence'])
                    })
                else:
                    logger.warning(f"Некорректный результат слинга: {result}. Помечено как unrelated.")
                    validated_results.append({
                        'message_id': 0, # или None, если message_id неизвестен
                        'related': False,
                        'thread_id': None,
                        'confidence': 0.0
                    })

            return validated_results

        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON слинга: {e}, ответ: {response}")
            return []
        except Exception as e:
            logger.error(f"Ошибка парсинга ответа слинга: {e}")
            return []

    def _parse_batch_classification_response(self, response: str) -> List[Dict]:
        """Парсит ответ пакетной классификации"""
        try:
            # Очищаем ответ
            cleaned_response = response.strip()
            if cleaned_response.startswith('```json'):
                cleaned_response = cleaned_response[7:]
            if cleaned_response.endswith('```'):
                cleaned_response = cleaned_response[:-3]
            cleaned_response = cleaned_response.strip()

            # Парсим JSON
            data = json.loads(cleaned_response)
            results = data.get('results', [])

            # Валидируем и сортируем результаты
            validated_results = []
            for result in sorted(results, key=lambda x: x.get('message_index', 0)):
                if all(key in result for key in ['message_index', 'classification', 'confidence']):
                    validated_results.append({
                        'classification': result['classification'],
                        'confidence': float(result['confidence']),
                        'title': result.get('title')
                    })
                else:
                    logger.warning(f"Некорректный результат классификации: {result}. Помечено как 'other'.")
                    validated_results.append({
                        'classification': 'other',
                        'confidence': 0.0,
                        'title': None
                    })

            return validated_results

        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON классификации: {e}, ответ: {response}")
            # Пытаемся извлечь данные с помощью regex как запасной вариант
            return self._parse_with_regex(response)
        except Exception as e:
            logger.error(f"Ошибка парсинга ответа классификации: {e}")
            return []

    def _parse_with_regex(self, response: str) -> List[Dict]:
        """Резервный парсинг с помощью regex"""
        try:
            results = []

            # Ищем classification паттерны
            classification_pattern = r'"classification":\s*"(\w+)"'
            confidence_pattern = r'"confidence":\s*([0-9.]+)'
            title_pattern = r'"title":\s*"([^"]*)"'

            classifications = re.findall(classification_pattern, response)
            confidences = re.findall(confidence_pattern, response)
            titles = re.findall(title_pattern, response)

            for i in range(max(len(classifications), len(confidences))):
                classification = classifications[i] if i < len(classifications) else 'other'
                confidence = float(confidences[i]) if i < len(confidences) else 0.5
                title = titles[i] if i < len(titles) else None

                results.append({
                    'classification': classification,
                    'confidence': confidence,
                    'title': title
                })

            logger.warning(f"Использован резервный парсинг regex для классификации. Результаты: {results}")
            return results[:10]  # Ограничиваем количество результатов

        except Exception as e:
            logger.error(f"Ошибка regex парсинга: {e}")
            return []

    async def _apply_classification_result(self, message: Dict, result: Dict) -> bool:
        """Применяет результат классификации к сообщению"""
        try:
            if result['classification'] in ['goal', 'blocker'] and result['confidence'] > 0.6:
                title = result['title'] or message['message_text'][:50]
                # Создаем новый тред с классификацией, определенной AI
                thread_id = self.db.create_thread(title, result['classification'])

                if thread_id > 0:
                    # Привязываем сообщение к новому треду, устанавливая его классификацию
                    self.db.update_message_thread(
                        message['message_id'],
                        thread_id,
                        result['classification'] # <-- Классификация устанавливается из результата AI
                    )
                    logger.debug(f"Создан тред {thread_id} (классификация: {result['classification']}) для сообщения {message['message_id']}")
                    return True
                else:
                    logger.error(f"Ошибка создания треда для сообщения {message['message_id']}")
                    return False
            else:
                # Если классификация 'other' или уверенность низкая, не создаем тред
                self.db.update_message_thread(message['message_id'], None, 'other')
                logger.debug(f"Сообщение {message['message_id']} помечено как 'other', тред не создан.")
                return True

        except Exception as e:
            logger.error(f"Ошибка применения классификации: {e}")
            return False

    async def _fallback_individual_processing(self, messages_batch: List[Dict], active_threads: List[Dict]) -> int:
        """Резервная индивидуальная обработка при ошибке пакетной"""
        processed_count = 0
        for message in messages_batch:
            try:
                await self.three_step_classification(message, active_threads)
                processed_count += 1
                await asyncio.sleep(0.1)  # Небольшая пауза между запросами
            except Exception as e:
                logger.error(f"Ошибка индивидуальной классификации: {e}")
        return processed_count

    async def _fallback_individual_classification(self, messages_batch: List[Dict]) -> int:
        """Резервная индивидуальная классификация"""
        return await self._fallback_individual_processing(messages_batch, [])

    # Старые методы для обратной совместимости и индивидуальной обработки
    async def three_step_classification(self, message_data: Dict, active_threads: List[Dict]):
        """Индивидуальная трехступенчатая классификация"""
        try:
            message_id = message_data['message_id']
            message_text = message_data['message_text']

            logger.debug(f"Индивидуальная классификация сообщения {message_id}")

            # Шаг 1: Проверка ответа/реплая
            if await self._step1_check_reply(message_data):
                return

            # Шаг 2: Семантический слинг
            if await self._step2_semantic_sling(message_data, message_text, active_threads):
                return

            # Шаг 3: Классификация новой сущности
            await self._step3_new_entity_classification(message_data, message_text)

        except Exception as e:
            logger.error(f"Ошибка трехступенчатой классификации для сообщения {message_data['message_id']}: {e}")

    async def _step1_check_reply(self, message_data: Dict) -> bool:
        """Шаг 1: Проверка ответа/реплая"""
        try:
            if message_data.get('parent_message_id'):
                parent_thread = self.db.get_message_thread_by_parent(message_data['parent_message_id'])
                if parent_thread:
                    # Сообщение-реплай наследует тред и классификацию родителя
                    self.db.update_message_thread(
                        message_data['message_id'],
                        parent_thread['thread_id'],
                        parent_thread['classification_id']
                    )
                    logger.info(
                        f"Сообщение {message_data['message_id']} привязано к треду {parent_thread['thread_id']} (наследование от родителя, классификация: {parent_thread['classification_id']})")
                    return True
            return False
        except Exception as e:
            logger.error(f"Ошибка в шаге 1 для сообщения {message_data['message_id']}: {e}")
            return False

    async def _step2_semantic_sling(self, message_data: Dict, message_text: str, active_threads: List[Dict]) -> bool:
        """Шаг 2: Семантический слинг (индивидуальный вызов, если пакетный не используется)"""
        try:
            # Используем индивидуальный вызов AI клиента, если пакетный не сработал
            # ВАЖНО: Этот метод (semantic_sling_schema_c) должен быть реализован в ai_client
            # и использовать обновленную логику, аналогичную пакетному промпту
            sling_result = await self.ai_client.semantic_sling_schema_c(message_text, active_threads)
            if sling_result.get('related') and sling_result.get('thread_id'):
                thread = self.db.get_thread_by_id(sling_result['thread_id'])
                if thread:
                    # Привязываем сообщение к найденному треду, используя его классификацию
                    self.db.update_message_thread(
                        message_data['message_id'],
                        sling_result['thread_id'],
                        thread['classification_id']
                    )
                    logger.info(
                        f"Сообщение {message_data['message_id']} привязано к треду {sling_result['thread_id']} (семантический слинг, классификация: {thread['classification_id']})")
                    return True
            return False
        except Exception as e:
            logger.error(f"Ошибка в шаге 2 для сообщения {message_data['message_id']}: {e}")
            return False

    async def _step3_new_entity_classification(self, message_data: Dict, message_text: str):
        """Шаг 3: Классификация новой сущности (индивидуальный вызов)"""
        try:
            # Используем индивидуальный вызов AI клиента
            # ВАЖНО: Этот метод (classify_message_schema_b) должен быть реализован в ai_client
            # и использовать обновленную логику, аналогичную пакетному промпту
            classification_result = await self.ai_client.classify_message_schema_b(message_text)
            if classification_result.get('classification') in ['goal', 'blocker']:
                thread_id = self.db.create_thread(
                    classification_result.get('title') or message_text[:50],
                    classification_result['classification']
                )
                if thread_id > 0:
                    # Привязываем сообщение к новому треду, устанавливая его классификацию
                    self.db.update_message_thread(
                        message_data['message_id'],
                        thread_id,
                        classification_result['classification']
                    )
                    logger.info(f"Создан новый тред {thread_id} (классификация: {classification_result['classification']}) для сообщения {message_data['message_id']}")
                else:
                    logger.error(f"Ошибка создания треда для сообщения {message_data['message_id']}")
            else:
                self.db.update_message_thread(message_data['message_id'], None, 'other')
                logger.info(f"Сообщение {message_data['message_id']} помечено как 'other' (индивидуальная классификация)")
        except Exception as e:
            logger.error(f"Ошибка в шаге 3 для сообщения {message_data['message_id']}: {e}")

    def get_classification_stats(self) -> Dict:
        """Возвращает статистику по классификации"""
        try:
            total_messages = len(self.db.get_messages_for_period(days=30))
            unprocessed = len(self.db.get_unprocessed_messages())
            processed = total_messages - unprocessed

            return {
                "total_messages": total_messages,
                "processed": processed,
                "unprocessed": unprocessed,
                "processing_rate": f"{(processed / total_messages * 100):.1f}%" if total_messages > 0 else "0%",
                "batch_size": self.batch_size
            }
        except Exception as e:
            logger.error(f"Ошибка получения статистики классификации: {e}")
            return {}
