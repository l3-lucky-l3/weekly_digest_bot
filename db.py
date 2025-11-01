import sqlite3
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str = "data/database.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Инициализация базы данных и создание таблиц"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Таблица для AI моделей
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS ai_models (
                        name TEXT UNIQUE NOT NULL,
                        model_path TEXT NOT NULL
                    )
                ''')

                # Таблица для отслеживаемых чатов
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS monitored_chats (
                        chat_id BIGINT PRIMARY KEY UNIQUE NOT NULL
                    )
                ''')

                conn.commit()
        except Exception as e:
            logger.error(f"Ошибка инициализации БД: {e}")
            raise

    # Методы для работы с AI моделями
    def get_all_models(self) -> Dict[str, str]:
        """Получает все AI модели из базы данных"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name, model_path FROM ai_models")
                rows = cursor.fetchall()
                return {name: model_path for name, model_path in rows}
        except Exception as e:
            logger.error(f"Ошибка получения моделей: {e}")
            return {}

    def add_model(self, name: str, model_path: str) -> bool:
        """Добавляет новую AI модель в базу данных"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO ai_models (name, model_path) VALUES (?, ?)",
                    (name, model_path)
                )
                conn.commit()
                return True
        except sqlite3.IntegrityError:
            return False
        except Exception as e:
            logger.error(f"Ошибка добавления AI модели: {e}")
            return False

    def remove_model(self, name: str) -> bool:
        """Удаляет AI модель из базы данных"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM ai_models WHERE name = ?", (name,))
                conn.commit()
                if cursor.rowcount > 0:
                    return True
                else:
                    return False
        except Exception as e:
            logger.error(f"Ошибка удаления AI модели: {e}")
            return False

    # Методы для работы с отслеживаемыми чатами
    def add_monitored_chat(self, chat_id: int) -> bool:
        """Добавляет чат для мониторинга"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR REPLACE INTO monitored_chats (chat_id) VALUES (?)",
                    (chat_id,)
                )
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Ошибка добавления чата: {e}")
            return False

    def remove_monitored_chat(self, chat_id: int) -> bool:
        """Удаляет чат из мониторинга"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM monitored_chats WHERE chat_id = ?", (chat_id,))
                conn.commit()
                if cursor.rowcount > 0:
                    return True
                return False
        except Exception as e:
            logger.error(f"Ошибка удаления чата: {e}")
            return False

    def get_monitored_chats(self) -> List[Dict]:
        """Получает список всех отслеживаемых чатов"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT chat_id FROM monitored_chats")
                rows = cursor.fetchall()
                return [row[0] for row in rows]
        except Exception as e:
            logger.error(f"Ошибка получения чатов: {e}")
            return []
