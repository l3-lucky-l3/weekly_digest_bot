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
        """Обрабатывает необработанные сообщения с пакетной классификацией"""
        try:
            unprocessed_messages = self.db.get_unprocessed_messages()
            if not unprocessed_messages:
                logger.info("Нет необработанных сообщений")
                return 0

            active_threads = self.db.get_active_threads_with_messages(days=7)
            logger.info(f"Найдено {len(unprocessed_messages)} необработанных сообщений")

            # Разбиваем на пакеты
            batches = [unprocessed_messages[i:i + self.batch_size]
                       for i in range(0, len(unprocessed_messages), self.batch_size)]

            total_processed = 0
            for batch_num, batch in enumerate(batches, 1):
                logger.info(f"Обработка пакета {batch_num}/{len(batches)} ({len(batch)} сообщений)")
                processed_in_batch = await self.process_batch(batch, active_threads)
                total_processed += processed_in_batch

                # Добавляем паузу между пакетами чтобы дать боту "подышать"
                if batch_num < len(batches):
                    await asyncio.sleep(0.1)  # 100ms пауза

            logger.info(f"Обработка завершена. Всего обработано: {total_processed}")
            return total_processed

        except Exception as e:
            logger.error(f"Ошибка обработки необработанных сообщений: {e}")
            return 0

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
                    thread = self.db.get_thread_by_id(sling_results[i]['thread_id'])
                    if thread:
                        self.db.update_message_thread(
                            message['message_id'],
                            sling_results[i]['thread_id'],
                            thread['classification_id']
                        )
                        processed_count += 1
                        logger.debug(
                            f"Пакетный слинг: сообщение {message['message_id']} → тред {sling_results[i]['thread_id']}")
                    else:
                        remaining_messages.append(message)
                else:
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
                    if await self._apply_classification_result(message, result):
                        processed_count += 1
                else:
                    # Если не хватило результатов, помечаем как 'other'
                    self.db.update_message_thread(message['message_id'], None, 'other')
                    processed_count += 1

            logger.debug(f"Шаг 3: пакетная классификация обработала: {processed_count}")
            return processed_count

        except Exception as e:
            logger.error(f"Ошибка пакетной классификации: {e}")
            # Резервный вариант: индивидуальная обработка
            return await self._fallback_individual_classification(messages_batch)

    def _create_batch_sling_prompt(self, messages_batch: List[Dict], active_threads: List[Dict]) -> str:
        """Создает промпт для пакетного семантического слинга"""

        # Форматируем треды для контекста
        threads_context = ""
        for i, thread in enumerate(active_threads[:15]):  # Ограничиваем количество тредов
            recent_messages = thread.get('messages', [])[:2]  # Берем 2 последних сообщения
            messages_preview = "; ".join([msg[:100] for msg in recent_messages])
            threads_context += f"{i + 1}. Тред #{thread['thread_id']} ({thread['classification_id']}): {thread['title']}\n   Сообщения: {messages_preview}\n\n"

        # Форматируем сообщения для классификации
        messages_context = ""
        for i, message in enumerate(messages_batch):
            messages_context += f"{i + 1}. Сообщение ID {message['message_id']}:\n   \"{message['message_text'][:300]}\"\n\n"

        prompt = f"""
Ты - ассистент для семантического связывания сообщений в IT-сообществе.
Определи, относятся ли следующие сообщения по смыслу к одному из существующих тредов.

СУЩЕСТВУЮЩИЕ ТРЕДЫ:
{threads_context}

СООБЩЕНИЯ ДЛЯ КЛАССИФИКАЦИИ:
{messages_context}

ПРОЦЕСС АНАЛИЗА:
1. Проанализируй КАЖДОЕ сообщение отдельно
2. Сравни его с каждым существующим тредом
3. Если сообщение логически продолжает обсуждение в треде - свяжи их
4. Если сообщение НЕ относится ни к одному треду - оставь related: false

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
- "goal" - новая идея, проект, исследование или задача для выполнения
- "blocker" - проблема или обстоятельство, мешающее работе  
- "other" - обычное сообщение, не требующее отдельного треда

СООБЩЕНИЯ ДЛЯ КЛАССИФИКАЦИИ:
{messages_context}

ПРОЦЕСС КЛАССИФИКАЦИИ:
1. Проанализируй КАЖДОЕ сообщение отдельно
2. Определи тип: goal, blocker или other
3. Для goal/blocker придумай краткое название (3-5 слов)
4. Оцени уверенность от 0 до 1

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
                    validated_results.append({
                        'message_id': 0,
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

            return results[:10]  # Ограничиваем количество результатов

        except Exception as e:
            logger.error(f"Ошибка regex парсинга: {e}")
            return []

    async def _apply_classification_result(self, message: Dict, result: Dict) -> bool:
        """Применяет результат классификации к сообщению"""
        try:
            if result['classification'] in ['goal', 'blocker'] and result['confidence'] > 0.6:
                title = result['title'] or message['message_text'][:50]
                thread_id = self.db.create_thread(title, result['classification'])

                if thread_id > 0:
                    self.db.update_message_thread(
                        message['message_id'],
                        thread_id,
                        result['classification']
                    )
                    logger.debug(f"Создан тред {thread_id} для сообщения {message['message_id']}")
                    return True
                else:
                    logger.error(f"Ошибка создания треда для сообщения {message['message_id']}")
                    return False
            else:
                self.db.update_message_thread(message['message_id'], None, 'other')
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
                    self.db.update_message_thread(
                        message_data['message_id'],
                        parent_thread['thread_id'],
                        parent_thread['classification_id']
                    )
                    logger.info(
                        f"Сообщение {message_data['message_id']} привязано к треду {parent_thread['thread_id']} (наследование)")
                    return True
            return False
        except Exception as e:
            logger.error(f"Ошибка в шаге 1 для сообщения {message_data['message_id']}: {e}")
            return False

    async def _step2_semantic_sling(self, message_data: Dict, message_text: str, active_threads: List[Dict]) -> bool:
        """Шаг 2: Семантический слинг"""
        try:
            sling_result = await self.ai_client.semantic_sling_schema_c(message_text, active_threads)
            if sling_result.get('related') and sling_result.get('thread_id'):
                thread = self.db.get_thread_by_id(sling_result['thread_id'])
                if thread:
                    self.db.update_message_thread(
                        message_data['message_id'],
                        sling_result['thread_id'],
                        thread['classification_id']
                    )
                    logger.info(
                        f"Сообщение {message_data['message_id']} привязано к треду {sling_result['thread_id']} (семантический слинг)")
                    return True
            return False
        except Exception as e:
            logger.error(f"Ошибка в шаге 2 для сообщения {message_data['message_id']}: {e}")
            return False

    async def _step3_new_entity_classification(self, message_data: Dict, message_text: str):
        """Шаг 3: Классификация новой сущности"""
        try:
            classification_result = await self.ai_client.classify_message_schema_b(message_text)
            if classification_result.get('classification') in ['goal', 'blocker']:
                thread_id = self.db.create_thread(
                    classification_result.get('title') or message_text[:50],
                    classification_result['classification']
                )
                if thread_id > 0:
                    self.db.update_message_thread(
                        message_data['message_id'],
                        thread_id,
                        classification_result['classification']
                    )
                    logger.info(f"Создан новый тред {thread_id} для сообщения {message_data['message_id']}")
                else:
                    logger.error(f"Ошибка создания треда для сообщения {message_data['message_id']}")
            else:
                self.db.update_message_thread(message_data['message_id'], None, 'other')
                logger.info(f"Сообщение {message_data['message_id']} помечено как 'other'")
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