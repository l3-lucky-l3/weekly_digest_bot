import os
import logging
from dotenv import load_dotenv
from openai import OpenAI
from typing import Dict, List
from db import Database

load_dotenv()

logger = logging.getLogger(__name__)


class AIClient:
    def __init__(self, db_path: str = "data/database.db"):
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY не найден в .env файле")

        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.api_key,
        )

        # Инициализация базы данных
        self.db = Database(db_path)

        # Загружаем модели из базы данных
        self.models: Dict[str, str] = self.db.get_all_models()

        if not self.models:
            logger.warning("В базе данных нет AI моделей. Добавьте модели через команду /add_model")

    def analyze_chat_messages(self, messages: List[str]) -> str:
        """Анализирует сообщения из чата и возвращает суммаризацию"""
        if not self.models:
            return "❌ Нет доступных AI моделей для анализа"

        # Объединяем сообщения для анализа
        context = "\n".join(
            [f"Сообщение {i + 1}: {msg}" for i, msg in enumerate(messages[-50:])])  # Берем последние 50 сообщений

        prompt = f"""
Проанализируй следующие сообщения из чата и создай краткую сводку основных тем, вопросов и обсуждений:

{context}

Создай структурированную сводку в формате:
1. Основные темы обсуждения
2. Ключевые вопросы
3. Важные моменты
4. Рекомендации или выводы

Будь кратким и информативным.
"""

        try:
            # Используем первую доступную модель
            model_key = list(self.models.keys())[0]
            return self.send_request(prompt, model_key)
        except Exception as e:
            logger.error(f"Ошибка анализа сообщений: {e}")
            # Пробуем другие модели при ошибке
            for model_key in list(self.models.keys())[1:]:
                try:
                    return self.send_request(prompt, model_key)
                except Exception:
                    continue
            return f"❌ Все AI модели недоступны для анализа: {str(e)}"

    def format_for_channel(self, content: str, style: str = "professional") -> str:
        """Форматирует контент для постинга в канал"""
        if not self.models:
            return content  # Возвращаем как есть, если нет моделей

        prompt = f"""
Отформатируй следующий текст для постинга в Telegram канал в {style} стиле:

{content}

Сделай текст:
- Структурированным и легко читаемым
- С использованием эмодзи для наглядности
- С четкими разделами
- Оптимизированным для Telegram (не слишком длинным)

Верни только отформатированный текст без дополнительных комментариев.
"""

        try:
            model_key = list(self.models.keys())[0]
            return self.send_request(prompt, model_key)
        except Exception as e:
            logger.error(f"Ошибка форматирования: {e}")
            return content  # Возвращаем оригинальный контент при ошибке

    def send_request(self, message: str, model_key: str = None) -> str:
        """Отправляет запрос к AI с автоматическим переключением моделей при ошибках"""
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
                logger.info(f"🔄 Пробуем модель: {current_model_key} -> {model}")

                completion = self.client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": message}],
                    max_tokens=2000
                )

                logger.info(f"✅ Успешно использована модель: {current_model_key}")
                return completion.choices[0].message.content

            except Exception as e:
                last_error = e
                logger.warning(f"❌ Модель {current_model_key} недоступна: {str(e)}")
                continue

        # Если все модели недоступны
        error_msg = f"Все AI модели недоступны. Последняя ошибка: {str(last_error)}"
        logger.error(error_msg)
        raise Exception(error_msg)

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
            "monitored_chats": len(self.db.get_monitored_chats()),
            "total_models": self.db.get_models_count()
        }
