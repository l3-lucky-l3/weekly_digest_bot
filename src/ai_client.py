import os
import logging
import asyncio
from dotenv import load_dotenv
from openai import OpenAI
from typing import Dict, List

load_dotenv()

logger = logging.getLogger(__name__)


class AIClient:
    def __init__(self):
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY не найден в .env файле")

        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.api_key,
        )

        # Инициализация базы данных
        from db import Database
        self.db = Database()

        # Загружаем модели из базы данных
        self.models: Dict[str, str] = self.db.get_all_models()

    def load_prompt(self, prompt_name: str) -> str:
        """Загружает промпт из файла"""
        try:
            prompt_path = os.path.join(os.path.dirname(__file__), "prompts", f"{prompt_name}.md")
            with open(prompt_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Ошибка загрузки промпта {prompt_name}: {e}")
            return f"Промпт {prompt_name} не найден"

    async def send_request_with_retry(self, message: str, model_key: str = None, max_retries: int = 3) -> str:
        """Отправляет запрос с повторными попытками"""
        last_error = None
        for attempt in range(max_retries):
            try:
                return await self.send_request(message, model_key)
            except Exception as e:
                last_error = e
                logger.warning(f"Попытка {attempt + 1}/{max_retries} не удалась: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Экспоненциальная задержка

        # После всех неудачных попыток
        error_msg = f"Все {max_retries} попыток не удались. Последняя ошибка: {str(last_error)}"
        logger.error(error_msg)
        raise Exception(error_msg)

    async def send_request(self, message: str, model_key: str = None) -> str:
        """Отправляет запрос к AI с автоматическим переключением моделей при ошибках"""
        logger.info(f"Отправка запроса к LLM. Длина: {len(message)} символов")

        if not self.models:
            raise Exception("Нет доступных AI моделей")

        # Если модель не указана, используем первую доступную
        if model_key is None:
            model_key = list(self.models.keys())[0]

        # Пробуем указанную модель сначала
        models_to_try = [model_key] + [m for m in self.models.keys() if m != model_key]

        last_error = None
        for current_model_key in models_to_try:
            try:
                model = self.models[current_model_key]

                completion = self.client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": message}],
                    max_tokens=2000
                )

                response = completion.choices[0].message.content
                logger.info(f"Получен ответ от LLM. Длина: {len(response)} символов")
                return response

            except Exception as e:
                last_error = e
                continue

        # Если все модели недоступны
        error_msg = f"Все AI модели недоступны. Последняя ошибка: {str(last_error)}"
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
    "Цель" - это новая идее, проект, исследование или задача, которую необходимо выполнить или проработать в рамках комьюнити. 
    Это высокоуровневое, широкое и долгосрочное описание желаемого результата.

    "Блокер" - это любое событие, проблема или обстоятельство, которое мешает или делает невозможным 
    выполнение запланированных задач в рамках проектов и достижения целей.

    РУКОВОДСТВА:
    - p3 express: приоритизация по принципу "самое важное сейчас"
    - p5 express: фокус на практической реализации
    - Руководства: https://omimo.org/ru/

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
            logger.error(f"Ошибка классификации сообщения: {e}")
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
    "Цель" - новая идее, проект, исследование или задача.
    "Блокер" - проблема или обстоятельство, мешающее работе.

    РУКОВОДСТВА:
    - p3 express: приоритизация по принципу "самое важное сейчас"
    - p5 express: фокус на практической реализации
    - Руководства: https://omimo.org/ru/

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
            logger.error(f"Ошибка семантического слинга: {e}")
            return {"related": False, "thread_id": None, "confidence": 0, "reason": str(e)}

    async def summarize_for_monday_schema_a(self, threads_data: List[Dict]) -> str:
        """
        Схема А: Суммаризация для понедельничного поста (цели/блокеры)
        """
        system_prompt = """
    Ты - ассистент для создания еженедельного дайджеста IT-сообщества.
    На основе обсуждений за неделю создай предложения целей и блокеров на следующую неделю.

    ОПРЕДЕЛЕНИЯ:
    "Цель" - новая идее, проект, исследование или задача для выполнения.
    "Блокер" - проблема или обстоятельство, мешающее работе.

    РУКОВОДСТВА:
    - p3 express: приоритизация по принципу "самое важное сейчас"  
    - p5 express: фокус на практической реализации
    - Руководства: https://omimo.org/ru/
    - Будь конкретным и ориентированным на действие
    - Используй маркдаун для форматирования

    Формат ответа:
    🎯 Цели недели:
    1. [Название цели] - [краткое описание и действия]
    2. [Название цели] - [краткое описание и действия]

    🛑 Основные блокеры:
    • [Название блокера] - [описание проблемы и что мешает]
    • [Название блокера] - [описание проблемы и что мешает]

    💡 Рекомендации:
    - [практическая рекомендация 1]
    - [практическая рекомендация 2]
    """

        # Группируем треды по классификации
        goals = [t for t in threads_data if t['classification_id'] == 'goal']
        blockers = [t for t in threads_data if t['classification_id'] == 'blocker']

        user_prompt = f"""
    На основе следующих тредов за неделю создай предложения целей и блокеров:

    ЦЕЛИ (Goals):
    {self._format_threads_for_summary(goals)}

    БЛОКЕРЫ (Blockers):
    {self._format_threads_for_summary(blockers)}

    Создай структурированный пост с приоритетными целями и блокерами на следующую неделю.
    """

        try:
            return await self.send_request_with_retry(system_prompt + user_prompt)
        except Exception as e:
            logger.error(f"Ошибка суммаризации для понедельника: {e}")
            return "❌ Не удалось создать суммаризацию для понедельничного поста"

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
            # Упрощенный парсинг JSON (в реальности нужно использовать json.loads с обработкой ошибок)
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
            logger.error(f"Ошибка парсинга ответа классификации: {e}")
            return {"classification": "other", "confidence": 0, "reason": str(e), "title": None}

    def _parse_sling_response(self, response: str) -> Dict:
        """Парсит ответ семантического слинга"""
        try:
            # Упрощенный парсинг (в реальности нужно использовать json.loads)
            if '"related": true' in response and 'thread_id' in response:
                # Извлекаем thread_id из ответа
                import re
                thread_id_match = re.search(r'"thread_id":\s*(\d+)', response)
                if thread_id_match:
                    return {
                        "related": True,
                        "thread_id": int(thread_id_match.group(1)),
                        "confidence": 0.7,
                        "reason": "Семантическая связь найдена"
                    }
            return {"related": False, "thread_id": None, "confidence": 0, "reason": "Связь не найдена"}
        except Exception as e:
            logger.error(f"Ошибка парсинга ответа слинга: {e}")
            return {"related": False, "thread_id": None, "confidence": 0, "reason": str(e)}

    def _format_threads_for_summary(self, threads: List[Dict]) -> str:
        """Форматирует треды для суммаризации"""
        if not threads:
            return "Нет тредов"

        result = []
        for thread in threads:
            result.append(f"- {thread['title']} (ID: {thread['thread_id']})")
            if thread['messages']:
                result.append(f"  Сообщения: {', '.join(thread['messages'][:2])}")
        return "\n".join(result)

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
            logger.error(f"Ошибка добавления AI модели: {e}")
            return False

    def remove_model(self, model_key: str) -> bool:
        """Удаляет AI модель из базы данных"""
        try:
            success = self.db.remove_model(model_key)
            if success and model_key in self.models:
                del self.models[model_key]
            return success
        except Exception as e:
            logger.error(f"Ошибка удаления AI модели: {e}")
            return False

    def get_stats(self) -> Dict[str, int]:
        """Возвращает статистику"""
        return {
            "ai_models": len(self.models),
        }
