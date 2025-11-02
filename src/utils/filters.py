from aiogram.filters import Filter
from aiogram.types import Message


class SourceTopicsFilter(Filter):
    def __init__(self, db, main_chat_id: str):
        self.db = db
        self.main_chat_id = main_chat_id

    async def __call__(self, message: Message) -> bool:
        # Проверяем, что сообщение из основного чата
        if str(message.chat.id) != self.main_chat_id:
            return False

        # Получаем список топиков-источников
        source_topics = self.db.get_source_topics()
        source_topic_ids = [topic['topic_id'] for topic in source_topics]

        # Проверяем, что сообщение из нужного топика
        return (hasattr(message, 'message_thread_id') and
                message.message_thread_id in source_topic_ids)
