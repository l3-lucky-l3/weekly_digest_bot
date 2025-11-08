import os
import logging
import asyncio
from dotenv import load_dotenv
from openai import AsyncOpenAI
from typing import Dict, List

load_dotenv()

logger = logging.getLogger(__name__)


class AIClient:
    def __init__(self, db):
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY не найден в .env файле")

        # Используем асинхронного клиента
        self.client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.api_key,
            timeout=30.0,  # Таймаут 30 секунд
            max_retries=2  # Максимум 2 попытки
        )

        self.db = db
        self.models: Dict[str, str] = self.db.get_all_models()

    async def send_request_with_retry(self, message: str, model_key: str = None, max_retries: int = 2) -> str:
        """Отправляет запрос с повторными попытками"""
        last_error = None
        for attempt in range(max_retries):
            try:
                return await self.send_request(message, model_key)
            except asyncio.TimeoutError:
                logger.warning(f"⏰ Таймаут при попытке {attempt + 1}/{max_retries}")
                last_error = "Timeout"
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
            except Exception as e:
                last_error = e
                logger.warning(f"🔄 Попытка {attempt + 1}/{max_retries} не удалась: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)

        error_msg = f"❌ Все {max_retries} попыток не удались. Последняя ошибка: {str(last_error)}"
        logger.error(error_msg)
        raise Exception(error_msg)

    async def send_request(self, message: str, model_key: str = None) -> str:
        """Отправляет асинхронный запрос к AI"""
        logger.info(f"📨 Отправка запроса к LLM. Длина: {len(message)} символов")

        if not self.models:
            raise Exception("❌ Нет доступных AI моделей")

        # Если модель не указана, используем первую доступную
        if model_key is None:
            model_key = list(self.models.keys())[0]

        # Пробуем указанную модель сначала
        models_to_try = [model_key] + [m for m in self.models.keys() if m != model_key]

        last_error = None
        for current_model_key in models_to_try:
            try:
                model = self.models[current_model_key]
                logger.info(f"🔄 Используется модель: {current_model_key}")

                # Асинхронный вызов с таймаутом
                completion = await asyncio.wait_for(
                    self.client.chat.completions.create(
                        model=model,
                        messages=[{"role": "user", "content": message}],
                        max_tokens=2000
                    ),
                    timeout=25.0  # Таймаут 25 секунд на запрос
                )

                response = completion.choices[0].message.content
                logger.info(f"✅ Получен ответ от LLM. Длина: {len(response)} символов")
                return response

            except asyncio.TimeoutError:
                logger.warning(f"⏰ Таймаут при использовании модели {current_model_key}")
                last_error = "Timeout"
                continue
            except Exception as e:
                logger.warning(f"❌ Модель {current_model_key} недоступна: {e}")
                last_error = e
                continue

        error_msg = f"❌ Все AI модели недоступны. Последняя ошибка: {str(last_error)}"
        logger.error(error_msg)
        raise Exception(error_msg)

    # === Базовые AI-схемы ===

    async def classify_message_schema_b(self, message: str, active_threads: List[Dict] = None) -> Dict:
        """
        Схема Б: Классификация нового сообщения
        Определяет, является ли сообщение 'goal' или 'blocker'
        """
        system_prompt = """
Ты - классификатор сообщений для IT-сообщества. 
Проанализируй сообщение и определи его тип.

ОПРЕДЕЛЕНИЯ:
"Цель" - это новая идея, проект, исследование или задача, которую необходимо выполнить или проработать в рамках комьюнити. 
Это высокоуровневое, широкое и долгосрочное описание желаемого результата.

"Блокер" - это любое событие, проблема или обстоятельство, которое мешает или делает невозможным 
выполнение запланированных задач в рамках проектов и достижения целей.

РУКОВОДСТВА:
- p3 express: приоритизация по принципу "самое важное сейчас"
- p5 express: фокус на практической реализации

Верни ответ в формате JSON:
{
    "classification": "goal" | "blocker" | "other",
    "confidence": число от 0 до 1,
    "reason": "обоснование решения",
    "title": "краткое название для треда (если classification не 'other')"
}
"""

        user_prompt = f"""
Сообщение для классификации: "{message}"

Проанализируй и классифицируй это сообщение.
"""

        try:
            response = await self.send_request_with_json(system_prompt + user_prompt)
            return self._parse_classification_response(response)
        except Exception as e:
            logger.error(f"❌ Ошибка классификации сообщения: {e}")
            return {"classification": "other", "confidence": 0, "reason": str(e), "title": None}

    async def semantic_sling_schema_c(self, message: str, active_threads: List[Dict]) -> Dict:
        """
        Схема В: Семантический слинг
        Проверяет привязку сообщения к существующим тредам
        """
        system_prompt = """
Ты - ассистент для семантического связывания сообщений. 
Определи, относится ли новое сообщение по смыслу к одному из существующих тредов.

ОПРЕДЕЛЕНИЯ:
"Цель" - новая идея, проект, исследование или задача.
"Блокер" - проблема или обстоятельство, мешающее работе.

РУКОВОДСТВА:
- p3 express: приоритизация по принципу "самое важное сейчас"
- p5 express: фокус на практической реализации

Верни ответ в формате JSON:
{
    "related": true | false,
    "thread_id": номер_треда | null,
    "confidence": число от 0 до 1,
    "reason": "обоснование решения"
}
"""

        # Формируем список активных тредов для контекста
        threads_context = ""
        for thread in active_threads:
            threads_context += f"\nТред {thread['thread_id']} ({thread['classification_id']}): {thread['title']}"
            if thread['messages']:
                recent_messages = thread['messages'][-3:]  # Последние 3 сообщения
                threads_context += f"\nПоследние сообщения: {' | '.join(recent_messages)}"

        user_prompt = f"""
Активные треды:{threads_context}

Новое сообщение: "{message}"

Определи, относится ли новое сообщение к одному из существующих тредов по смыслу.
Если относится, укажи ID наиболее подходящего треда.
"""

        try:
            response = await self.send_request_with_json(system_prompt + user_prompt)
            return self._parse_sling_response(response)
        except Exception as e:
            logger.error(f"❌ Ошибка семантического слинга: {e}")
            return {"related": False, "thread_id": None, "confidence": 0, "reason": str(e)}

    # === Вспомогательные методы ===

    async def send_request_with_json(self, prompt: str, model_key: str = None) -> str:
        """Отправляет запрос с ожиданием JSON ответа"""
        response = await self.send_request_with_retry(
            prompt + "\n\nВерни ответ ТОЛЬКО в формате JSON, без дополнительного текста.",
            model_key
        )
        return response

    def _parse_classification_response(self, response: str) -> Dict:
        """Парсит ответ классификации"""
        try:
            import json
            # Пытаемся распарсить JSON
            data = json.loads(response)
            return {
                "classification": data.get("classification", "other"),
                "confidence": data.get("confidence", 0.5),
                "reason": data.get("reason", "Автоматическая классификация"),
                "title": data.get("title")
            }
        except json.JSONDecodeError:
            # Резервный парсинг если JSON невалидный
            if '"classification": "goal"' in response:
                return {"classification": "goal", "confidence": 0.8, "reason": "Автоматическая классификация",
                        "title": "Новая цель"}
            elif '"classification": "blocker"' in response:
                return {"classification": "blocker", "confidence": 0.8, "reason": "Автоматическая классификация",
                        "title": "Новый блокер"}
            else:
                return {"classification": "other", "confidence": 0.5, "reason": "Не удалось классифицировать",
                        "title": None}
        except Exception as e:
            logger.error(f"❌ Ошибка парсинга ответа классификации: {e}")
            return {"classification": "other", "confidence": 0, "reason": str(e), "title": None}

    def _parse_sling_response(self, response: str) -> Dict:
        """Парсит ответ семантического слинга"""
        try:
            import json
            import re

            # Пытаемся распарсить JSON
            data = json.loads(response)
            return {
                "related": data.get("related", False),
                "thread_id": data.get("thread_id"),
                "confidence": data.get("confidence", 0.0),
                "reason": data.get("reason", "Семантический анализ")
            }
        except json.JSONDecodeError:
            # Резервный парсинг
            if '"related": true' in response:
                thread_id_match = re.search(r'"thread_id":\s*(\d+)', response)
                thread_id = int(thread_id_match.group(1)) if thread_id_match else None
                return {
                    "related": True,
                    "thread_id": thread_id,
                    "confidence": 0.7,
                    "reason": "Семантическая связь найдена"
                }
            return {"related": False, "thread_id": None, "confidence": 0, "reason": "Связь не найдена"}
        except Exception as e:
            logger.error(f"❌ Ошибка парсинга ответа слинга: {e}")
            return {"related": False, "thread_id": None, "confidence": 0, "reason": str(e)}

    # === Методы для работы с AI моделями ===

    def get_available_models(self) -> str:
        """Возвращает список доступных AI моделей"""
        if not self.models:
            return "🤖 В базе данных нет AI моделей. Используйте /add_model для добавления."

        models_list = "\n".join([f"• {key}: {model}" for key, model in self.models.items()])
        return f"🤖 Доступные AI модели ({len(self.models)}):\n{models_list}"

    def add_model(self, model_key: str, model_value: str) -> bool:
        """Добавляет новую AI модель в базу данных"""
        try:
            success = self.db.add_model(model_key, model_value)
            if success:
                self.models[model_key] = model_value
            return success
        except Exception as e:
            logger.error(f"❌ Ошибка добавления AI модели: {e}")
            return False

    def remove_model(self, model_key: str) -> bool:
        """Удаляет AI модель из базы данных"""
        try:
            success = self.db.remove_model(model_key)
            if success and model_key in self.models:
                del self.models[model_key]
            return success
        except Exception as e:
            logger.error(f"❌ Ошибка удаления AI модели: {e}")
            return False

    def get_stats(self) -> Dict[str, int]:
        """Возвращает статистику"""
        return {
            "ai_models": len(self.models),
        }

    async def close(self):
        """Закрывает клиент"""
        await self.client.close()
