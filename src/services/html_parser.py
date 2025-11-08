# services/html_parser.py
import logging
from datetime import datetime
from bs4 import BeautifulSoup
import re

logger = logging.getLogger(__name__)


class HTMLParserService:
    def __init__(self, db):
        self.db = db

    async def parse_html_file(self, file_path: str) -> dict:
        """
        Парсит HTML файл с историей чата Telegram и сохраняет сообщения в БД
        """
        try:
            start_time = datetime.now()

            with open(file_path, 'r', encoding='utf-8') as file:
                html_content = file.read()

            soup = BeautifulSoup(html_content, 'html.parser')

            # Собираем статистику
            stats = {
                'total_messages': 0,
                'saved_messages': 0,
                'topics_found': set(),
                'processing_time': 0,
                'success': False,
                'error': None
            }

            # Ищем все сообщения (обычные и сервисные)
            messages = soup.find_all('div', id=re.compile(r'^message-?\d+$'))
            stats['total_messages'] = len(messages)

            if not messages:
                stats['error'] = "Не найдено сообщений в файле"
                return stats

            # Сначала собираем все сервисные сообщения о создании и переименовании топиков
            topic_creation_messages = self._extract_topic_creation_messages(messages)

            current_topic_id = None
            saved_count = 0

            for message in messages:
                try:
                    # Определяем topic_id из структуры сообщения
                    topic_id = self._extract_topic_id(message, topic_creation_messages)
                    if topic_id:
                        current_topic_id = topic_id
                        stats['topics_found'].add(topic_id)

                    # Парсим данные сообщения
                    message_data = self._parse_message(message, current_topic_id)
                    if message_data and message_data.get('message_text'):
                        # Сохраняем в БД
                        if self.db.save_message(message_data):
                            saved_count += 1
                            logger.debug(
                                f"Сообщение сохранено: {message_data['message_text'][:50]}... (дата: {message_data['created_at']})")

                except Exception as e:
                    logger.error(f"Ошибка парсинга сообщения: {e}")
                    continue

            stats['saved_messages'] = saved_count
            stats['topics_found'] = len(stats['topics_found'])
            stats['processing_time'] = (datetime.now() - start_time).total_seconds()
            stats['success'] = True

            logger.info(f"Парсинг завершен: {saved_count}/{len(messages)} сообщений сохранено")
            return stats

        except Exception as e:
            logger.error(f"Ошибка парсинга HTML файла: {e}")
            return {
                'success': False,
                'error': str(e),
                'total_messages': 0,
                'saved_messages': 0,
                'topics_found': 0,
                'processing_time': 0
            }

    def _extract_topic_creation_messages(self, messages) -> dict:
        """
        Извлекает из сервисных сообщений информацию о создании и переименовании топиков

        Returns:
            dict: {message_id: {'topic_name': str, 'created_at': datetime, 'type': 'creation'|'rename'}}
        """
        topic_messages = {}

        for message in messages:
            if self._is_service_message(message):
                # Пытаемся извлечь информацию о создании топика
                topic_name = self._extract_topic_name_from_service_message(message)
                created_at = self._extract_message_datetime(message)

                if topic_name and created_at:
                    message_id = self._extract_message_id(message)
                    if message_id:
                        topic_messages[message_id] = {
                            'topic_name': topic_name,
                            'created_at': created_at,
                            'type': 'creation'
                        }
                        logger.debug(
                            f"Найдено сервисное сообщение о создании топика: {topic_name} (message_id: {message_id})")

                # Пытаемся извлечь информацию о переименовании топика
                renamed_topic_name = self._extract_renamed_topic_name_from_service_message(message)
                if renamed_topic_name and created_at:
                    message_id = self._extract_message_id(message)
                    if message_id:
                        # Если уже есть запись о создании, обновляем её
                        if message_id in topic_messages:
                            topic_messages[message_id]['topic_name'] = renamed_topic_name
                            topic_messages[message_id]['type'] = 'rename'
                        else:
                            topic_messages[message_id] = {
                                'topic_name': renamed_topic_name,
                                'created_at': created_at,
                                'type': 'rename'
                            }
                        logger.debug(
                            f"Найдено сервисное сообщение о переименовании топика: {renamed_topic_name} (message_id: {message_id})")

        return topic_messages

    def _extract_renamed_topic_name_from_service_message(self, message) -> str:
        """
        Извлекает новое название топика из сервисного сообщения о переименовании
        """
        try:
            if not self._is_service_message(message):
                return None

            # Ищем текст сообщения
            body = message.find('div', class_='body')
            if body:
                text = body.get_text(strip=True)
                # Ищем паттерн переименования топика
                pattern = r'changed topic title to\s+«([^»]+)»'
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    return match.group(1)

                # Альтернативные паттерны для переименования
                patterns = [
                    r'изменил\(а\)\s+название\s+топика\s+на\s+«([^»]+)»',
                    r'переименовал\(а\)\s+топик\s+в\s+«([^»]+)»',
                    r'topic title changed to\s+«([^»]+)»',
                    r'название\s+топика\s+изменено\s+на\s+«([^»]+)»'
                ]

                for pattern in patterns:
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        return match.group(1)

        except Exception as e:
            logger.error(f"Ошибка извлечения нового названия топика из сервисного сообщения: {e}")

        return None

    def _extract_topic_id(self, message, topic_creation_messages: dict) -> int:
        """
        Извлекает ID топика из сообщения, учитывая сервисные сообщения о создании и переименовании топиков
        """
        try:
            # Если это сервисное сообщение о создании или переименовании топика - ищем topic_id по имени в БД
            if self._is_service_message(message):
                topic_name = self._extract_topic_name_from_service_message(message)
                renamed_topic_name = self._extract_renamed_topic_name_from_service_message(message)

                # Используем новое название если топик переименован
                target_topic_name = renamed_topic_name if renamed_topic_name else topic_name

                if target_topic_name:
                    # Ищем topic_id в БД по имени топика
                    source_topics = self.db.get_source_topics()
                    for topic in source_topics:
                        if topic['topic_name'] and target_topic_name.lower() in topic['topic_name'].lower():
                            logger.debug(f"Найден topic_id {topic['topic_id']} для топика '{target_topic_name}'")
                            return topic['topic_id']

            # Для обычных сообщений проверяем, не является ли это ответом на сервисное сообщение о создании/переименовании топика
            parent_message_id = self._extract_parent_message_id(message)
            if parent_message_id and parent_message_id in topic_creation_messages:
                topic_name = topic_creation_messages[parent_message_id]['topic_name']
                # Ищем topic_id в БД по имени топика
                source_topics = self.db.get_source_topics()
                for topic in source_topics:
                    if topic['topic_name'] and topic_name.lower() in topic['topic_name'].lower():
                        logger.debug(f"Найден topic_id {topic['topic_id']} для топика '{topic_name}' (через реплай)")
                        return topic['topic_id']

            # Стандартные методы поиска topic_id
            topic_links = message.find_all('a', href=True)
            for link in topic_links:
                href = link.get('href', '')
                topic_match = re.search(r'topic[_-]?(\d+)', href, re.IGNORECASE)
                if topic_match:
                    return int(topic_match.group(1))

            # Ищем в тексте сообщения упоминания топиков
            text_elements = message.find_all(text=True)
            for text in text_elements:
                topic_match = re.search(r'топик[_\s]*(\d+)', text, re.IGNORECASE)
                if topic_match:
                    return int(topic_match.group(1))

            return None

        except Exception as e:
            logger.error(f"Ошибка извлечения topic_id: {e}")
            return None

    def _extract_topic_name_from_service_message(self, message) -> str:
        """
        Извлекает название топика из сервисного сообщения
        """
        try:
            if not self._is_service_message(message):
                return None

            # Ищем текст сообщения
            body = message.find('div', class_='body')
            if body:
                text = body.get_text(strip=True)
                # Ищем паттерн создания топика
                pattern = r'created topic\s+«([^»]+)»'
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    return match.group(1)

                # Альтернативные паттерны
                patterns = [
                    r'создал\(а\)\s+топик\s+«([^»]+)»',
                    r'topic\s+«([^»]+)»\s+created',
                    r'топик\s+«([^»]+)»\s+создан'
                ]

                for pattern in patterns:
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        return match.group(1)

        except Exception as e:
            logger.error(f"Ошибка извлечения названия топика из сервисного сообщения: {e}")

        return None

    def _is_service_message(self, message) -> bool:
        """
        Проверяет, является ли сообщение сервисным
        """
        try:
            classes = message.get('class', [])
            return 'message' in classes and 'service' in classes
        except Exception as e:
            logger.error(f"Ошибка проверки сервисного сообщения: {e}")
            return False

    def _extract_message_datetime(self, message):
        """
        Извлекает дату и время из сообщения
        """
        try:
            # Ищем время в сообщении
            time_element = message.find('div', class_='date')
            if time_element:
                time_text = time_element.get('title', '')
                if time_text:
                    result_date = datetime.strptime(time_text, "%d.%m.%Y %H:%M:%S UTC+03:00")
                    return result_date

        except Exception as e:
            logger.error(f"Ошибка извлечения времени сообщения: {e}")
            return None

    def _extract_message_id(self, message) -> int:
        """
        Извлекает ID сообщения
        """
        try:
            if message.get('id'):
                id_match = re.search(r'message-?(\d+)', message.get('id', ''), re.IGNORECASE)
                if id_match:
                    return int(id_match.group(1))

        except Exception as e:
            logger.error(f"Ошибка извлечения message_id: {e}")
            return 0

    def _parse_message(self, message, topic_id: int) -> dict:
        """
        Парсит отдельное сообщение
        """
        try:
            # Пропускаем сервисные сообщения
            if self._is_service_message(message):
                return None

            message_id = self._extract_message_id(message)
            if not message_id:
                return None

            created_at = self._extract_message_datetime(message)
            if not created_at:
                logger.warning(f"Не удалось извлечь дату для сообщения {message_id}")
                return None

            message_data = {
                'message_id': message_id,
                'topic_id': topic_id,
                'message_text': '',
                'thread_id': None,
                'parent_message_id': None,
                'classification_id': None,
                'created_at': created_at
            }

            # Извлекаем текст сообщения
            message_text = self._extract_message_text(message)
            if not message_text:
                return None

            message_data['message_text'] = message_text

            # Извлекаем информацию о родительском сообщении (реплай)
            parent_message_id = self._extract_parent_message_id(message)
            if parent_message_id:
                if not self._is_parent_service_message(parent_message_id, message):
                    message_data['parent_message_id'] = parent_message_id

            return message_data

        except Exception as e:
            logger.error(f"Ошибка парсинга сообщения: {e}")
            return None

    def _is_parent_service_message(self, parent_message_id: int, current_message) -> bool:
        """
        Проверяет, является ли родительское сообщение сервисным
        """
        try:
            parent_selector = f'div[id="message-{parent_message_id}"], div[id="message{parent_message_id}"]'
            parent_message = current_message.find_previous_sibling(parent_selector)

            if not parent_message:
                soup = current_message.find_parent()
                if soup:
                    parent_message = soup.find('div', id=re.compile(f'^message-?{parent_message_id}$'))

            if parent_message:
                return self._is_service_message(parent_message)

            return False

        except Exception as e:
            logger.error(f"Ошибка проверки сервисного родителя: {e}")
            return False

    def _extract_message_text(self, message) -> str:
        """
        Извлекает текст сообщения
        """
        try:
            # Для обычных сообщений ищем блок с текстом
            text_body = message.find('div', class_='text')
            if text_body:
                text = text_body.get_text(strip=True)
                if text:
                    return self._clean_text(text)

            return ''

        except Exception as e:
            logger.error(f"Ошибка извлечения текста сообщения: {e}")
            return ''

    def _extract_parent_message_id(self, message) -> int:
        """
        Извлекает ID родительского сообщения (для реплаев)
        """
        try:
            reply_elements = message.find_all(class_=re.compile(r'reply_to', re.IGNORECASE))
            for element in reply_elements:
                links = element.find_all('a', href=True)
                for link in links:
                    href = link.get('href', '')
                    msg_match = re.search(r'go_to_message\((\d+)\)', href)
                    if msg_match:
                        return int(msg_match.group(1))
                    msg_match = re.search(r'message[_-]?(\d+)', href, re.IGNORECASE)
                    if msg_match:
                        return int(msg_match.group(1))

            return None

        except Exception as e:
            logger.error(f"Ошибка извлечения parent_message_id: {e}")
            return None

    def _clean_text(self, text: str) -> str:
        """
        Обрабатывает текст сообщения
        """
        if not text:
            return ''

        # Удаляем лишние пробелы и переносы строк
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()

        return text
