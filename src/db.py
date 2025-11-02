import os
import sqlite3
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str = None):
        # Определяем путь автоматически
        if db_path is None:
            # Если запущено в Docker - используем /app/data
            if os.path.exists("/app"):
                db_path = "/app/data/database.db"
            else:
                # Если запущено локально - используем data в корне проекта
                current_dir = os.path.dirname(os.path.abspath(__file__))
                project_root = os.path.dirname(current_dir)  # Поднимаемся из src/
                db_path = os.path.join(project_root, "data", "database.db")

        self.db_path = db_path
        # Создаем директорию для данных если её нет
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        logger.info(f"Используется база данных: {self.db_path}")
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

                # Таблица для топиков-источников (откуда брать сообщения)
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS source_topics (
                        topic_id INTEGER PRIMARY KEY UNIQUE NOT NULL,
                        topic_name TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                # Таблица для системных топиков (куда постить)
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS system_topics (
                        topic_type TEXT PRIMARY KEY UNIQUE NOT NULL,
                        topic_id INTEGER NOT NULL,
                        topic_name TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                # Таблица для сообщений с тредами
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS chat_messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        message_id INTEGER NOT NULL,
                        chat_id BIGINT NOT NULL,
                        topic_id INTEGER,
                        thread_id INTEGER,
                        parent_message_id INTEGER,
                        classification_id TEXT, -- 'goal', 'blocker', 'other'
                        message_text TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        processed BOOLEAN DEFAULT FALSE,
                        UNIQUE(message_id, chat_id)
                    )
                ''')

                # Таблица для тредов
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS message_threads (
                        thread_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT,
                        classification_id TEXT, -- 'goal', 'blocker'
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        is_active BOOLEAN DEFAULT TRUE
                    )
                ''')

                # Создаем индексы для производительности
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_thread_id ON chat_messages(thread_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_classification ON chat_messages(classification_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_created_at ON chat_messages(created_at)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_processed ON chat_messages(processed)')

                conn.commit()
                logger.info("База данных инициализирована с новыми таблицами")
        except Exception as e:
            logger.error(f"Ошибка инициализации БД: {e}")
            raise

    def add_source_topic(self, topic_id: int, topic_name: str = None) -> bool:
        """Добавляет топик-источник для парсинга"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR REPLACE INTO source_topics (topic_id, topic_name) VALUES (?, ?)",
                    (topic_id, topic_name)
                )
                conn.commit()
                logger.info(f"Топик-источник добавлен: ID {topic_id}, название: {topic_name}")
                return True
        except Exception as e:
            logger.error(f"Ошибка добавления топика-источника: {e}")
            return False

    def remove_source_topic(self, topic_id: int) -> bool:
        """Удаляет топик-источник"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM source_topics WHERE topic_id = ?", (topic_id,))
                conn.commit()
                if cursor.rowcount > 0:
                    logger.info(f"Топик-источник удален: ID {topic_id}")
                    return True
                return False
        except Exception as e:
            logger.error(f"Ошибка удаления топика-источника: {e}")
            return False

    def get_source_topics(self) -> List[Dict]:
        """Получает список всех топиков-источников"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT topic_id, topic_name FROM source_topics ORDER BY topic_id")
                rows = cursor.fetchall()
                return [{"topic_id": row[0], "topic_name": row[1]} for row in rows]
        except Exception as e:
            logger.error(f"Ошибка получения топиков-источников: {e}")
            return []

    # === МЕТОДЫ ДЛЯ СИСТЕМНЫХ ТОПИКОВ ===

    def set_system_topic(self, topic_type: str, topic_id: int, topic_name: str = None) -> bool:
        """Устанавливает системный топик (Conductor или Announcements)"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT OR REPLACE INTO system_topics 
                    (topic_type, topic_id, topic_name, updated_at) 
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)""",
                    (topic_type, topic_id, topic_name)
                )
                conn.commit()
                logger.info(f"Системный топик установлен: {topic_type} -> ID {topic_id}")
                return True
        except Exception as e:
            logger.error(f"Ошибка установки системного топика: {e}")
            return False

    def get_system_topic(self, topic_type: str) -> Optional[Dict]:
        """Получает системный топик по типу"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT topic_type, topic_id, topic_name FROM system_topics WHERE topic_type = ?",
                    (topic_type,)
                )
                row = cursor.fetchone()
                if row:
                    return {
                        "topic_type": row[0],
                        "topic_id": row[1],
                        "topic_name": row[2]
                    }
                return None
        except Exception as e:
            logger.error(f"Ошибка получения системного топика: {e}")
            return None

    # === МЕТОДЫ ДЛЯ СООБЩЕНИЙ ===

    def save_message(self, message_data: Dict) -> bool:
        """Сохраняет сообщение в базу"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO chat_messages 
                    (message_id, chat_id, topic_id, thread_id, parent_message_id, classification_id, message_text)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    message_data.get('message_id'),
                    message_data.get('chat_id'),
                    message_data.get('topic_id'),
                    message_data.get('thread_id'),
                    message_data.get('parent_message_id'),
                    message_data.get('classification_id'),
                    message_data.get('message_text')
                ))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Ошибка сохранения сообщения: {e}")
            return False

    def get_messages_for_period(self, days: int = 7) -> List[Dict]:
        """Получает сообщения за указанный период"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT * FROM chat_messages 
                    WHERE created_at >= datetime('now', ?) 
                    ORDER BY created_at DESC
                ''', (f'-{days} days',))

                rows = cursor.fetchall()
                columns = [description[0] for description in cursor.description]
                return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            logger.error(f"Ошибка получения сообщений: {e}")
            return []

    def get_messages_by_thread(self, thread_id: int) -> List[Dict]:
        """Получает все сообщения треда"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT * FROM chat_messages 
                    WHERE thread_id = ? 
                    ORDER BY created_at ASC
                ''', (thread_id,))

                rows = cursor.fetchall()
                columns = [description[0] for description in cursor.description]
                return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            logger.error(f"Ошибка получения сообщений треда: {e}")
            return []

    # === МЕТОДЫ ДЛЯ ТРЕДОВ ===

    def create_thread(self, title: str, classification_id: str) -> int:
        """Создает новый тред и возвращает его ID"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO message_threads (title, classification_id) VALUES (?, ?)",
                    (title, classification_id)
                )
                thread_id = cursor.lastrowid
                conn.commit()
                logger.info(f"Создан новый тред: ID {thread_id}, классификация: {classification_id}")
                return thread_id
        except Exception as e:
            logger.error(f"Ошибка создания треда: {e}")
            return -1

    def get_active_threads(self) -> List[Dict]:
        """Получает активные треды"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT * FROM message_threads 
                    WHERE is_active = TRUE 
                    ORDER BY created_at DESC
                ''')

                rows = cursor.fetchall()
                columns = [description[0] for description in cursor.description]
                return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            logger.error(f"Ошибка получения активных тредов: {e}")
            return []

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
