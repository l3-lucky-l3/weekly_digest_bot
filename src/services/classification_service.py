import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


class ClassificationService:
    def __init__(self, db, ai_client):
        self.db = db
        self.ai_client = ai_client

    async def process_unprocessed_messages(self):
        """Обрабатывает необработанные сообщения трехступенчатым методом"""
        try:
            unprocessed_messages = self.db.get_unprocessed_messages()
            if not unprocessed_messages:
                logger.info("Нет необработанных сообщений")
                return

            active_threads = self.db.get_active_threads_with_messages(days=7)
            logger.info(
                f"Найдено {len(unprocessed_messages)} необработанных сообщений и {len(active_threads)} активных тредов")

            processed_count = 0
            for message in unprocessed_messages:
                await self.three_step_classification(message, active_threads)
                processed_count += 1

            logger.info(f"Обработка завершена. Обработано сообщений: {processed_count}")

        except Exception as e:
            logger.error(f"Ошибка обработки необработанных сообщений: {e}")

    async def three_step_classification(self, message_data: Dict, active_threads: List[Dict]):
        """Трехступенчатый процесс классификации сообщения"""
        try:
            message_id = message_data['message_id']
            message_text = message_data['message_text']

            logger.debug(f"Классификация сообщения {message_id}: {message_text[:100]}...")

            # Шаг 1: Проверка ответа/реплая
            classification_result = await self._step1_check_reply(message_data)
            if classification_result:
                return

            # Шаг 2: Семантический слинг
            classification_result = await self._step2_semantic_sling(message_data, message_text, active_threads)
            if classification_result:
                return

            # Шаг 3: Классификация новой сущности
            await self._step3_new_entity_classification(message_data, message_text)

        except Exception as e:
            logger.error(f"Ошибка трехступенчатой классификации для сообщения {message_data['message_id']}: {e}")

    async def _step1_check_reply(self, message_data: Dict) -> bool:
        """Шаг 1: Проверка ответа/реплая"""
        try:
            if message_data['parent_message_id']:
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
            if sling_result['related'] and sling_result['thread_id']:
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
            if classification_result['classification'] in ['goal', 'blocker']:
                thread_id = self.db.create_thread(
                    classification_result['title'] or message_text[:50],
                    classification_result['classification']
                )
                if thread_id > 0:
                    self.db.update_message_thread(
                        message_data['message_id'],
                        thread_id,
                        classification_result['classification']
                    )
                    logger.info(
                        f"Создан новый тред {thread_id} для сообщения {message_data['message_id']} ({classification_result['classification']})")
                else:
                    logger.error(f"Ошибка создания треда для сообщения {message_data['message_id']}")
            else:
                # Помечаем как обработанное даже если не классифицировано
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
                "processing_rate": f"{(processed / total_messages * 100):.1f}%" if total_messages > 0 else "0%"
            }
        except Exception as e:
            logger.error(f"Ошибка получения статистики классификации: {e}")
            return {}
