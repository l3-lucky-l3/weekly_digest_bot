import sqlite3
import logging
from typing import Dict, List, Optional

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
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT UNIQUE NOT NULL,
                        model_path TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                # Таблица для отслеживаемых чатов
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS monitored_chats (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id TEXT UNIQUE NOT NULL,
                        chat_name TEXT,
                        is_active BOOLEAN DEFAULT 1,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                # Таблица для расписания постинга
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS posting_schedule (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        channel_id TEXT NOT NULL,
                        post_time TEXT NOT NULL,
                        is_active BOOLEAN DEFAULT 1,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                conn.commit()
                logger.info("База данных мониторинга инициализирована")
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
                logger.info(f"AI модель '{name}' добавлена в БД")
                return True
        except sqlite3.IntegrityError:
            logger.warning(f"AI модель '{name}' уже существует")
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
                    logger.info(f"AI модель '{name}' удалена из БД")
                    return True
                else:
                    logger.warning(f"AI модель '{name}' не найдена в БД")
                    return False
        except Exception as e:
            logger.error(f"Ошибка удаления AI модели: {e}")
            return False

    # Методы для работы с отслеживаемыми чатами
    def add_monitored_chat(self, chat_id: str, chat_name: str = "") -> bool:
        """Добавляет чат для мониторинга"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR REPLACE INTO monitored_chats (chat_id, chat_name) VALUES (?, ?)",
                    (chat_id, chat_name)
                )
                conn.commit()
                logger.info(f"Чат '{chat_name}' ({chat_id}) добавлен для мониторинга")
                return True
        except Exception as e:
            logger.error(f"Ошибка добавления чата: {e}")
            return False

    def remove_monitored_chat(self, chat_id: str) -> bool:
        """Удаляет чат из мониторинга"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM monitored_chats WHERE chat_id = ?", (chat_id,))
                conn.commit()
                if cursor.rowcount > 0:
                    logger.info(f"Чат {chat_id} удален из мониторинга")
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
                cursor.execute("SELECT chat_id, chat_name, is_active FROM monitored_chats")
                rows = cursor.fetchall()
                return [{"chat_id": row[0], "chat_name": row[1], "is_active": bool(row[2])} for row in rows]
        except Exception as e:
            logger.error(f"Ошибка получения чатов: {e}")
            return []

    # Методы для работы с расписанием
    def set_posting_schedule(self, channel_id: str, post_time: str) -> bool:
        """Устанавливает расписание постинга в канал"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR REPLACE INTO posting_schedule (channel_id, post_time) VALUES (?, ?)",
                    (channel_id, post_time)
                )
                conn.commit()
                logger.info(f"Расписание для канала {channel_id} установлено на {post_time}")
                return True
        except Exception as e:
            logger.error(f"Ошибка установки расписания: {e}")
            return False

    def get_posting_schedule(self) -> Optional[Dict]:
        """Получает текущее расписание постинга"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT channel_id, post_time FROM posting_schedule WHERE is_active = 1 LIMIT 1")
                row = cursor.fetchone()
                return {"channel_id": row[0], "post_time": row[1]} if row else None
        except Exception as e:
            logger.error(f"Ошибка получения расписания: {e}")
            return None

    def get_models_count(self) -> int:
        """Возвращает количество AI моделей в базе"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM ai_models")
                return cursor.fetchone()[0]
        except Exception as e:
            logger.error(f"Ошибка получения количества моделей: {e}")
            return 0