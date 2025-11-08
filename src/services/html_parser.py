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

        Args:
            file_path: путь к HTML файлу

        Returns:
            dict: результат парсинга
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

            current_topic_id = None
            saved_count = 0
            current_date = None

            for message in messages:
                try:
                    # Определяем topic_id из структуры сообщения
                    topic_id = self._extract_topic_id(message)
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
                result_date = datetime.strptime(time_text, "%d.%m.%Y %H:%M:%S UTC+03:00")
                return result_date

        except Exception as e:
            logger.error(f"Ошибка извлечения времени сообщения: {e}")
            return None

    def _extract_topic_id(self, message) -> int:
        """
        Извлекает ID топика из сообщения
        """
        try:
            # Ищем ссылки на топики в сообщении
            topic_links = message.find_all('a', href=True)
            for link in topic_links:
                href = link.get('href', '')
                # Ищем pattern топика в ссылке
                topic_match = re.search(r'topic[_-]?(\d+)', href, re.IGNORECASE)
                if topic_match:
                    return int(topic_match.group(1))

            # Ищем в тексте сообщения упоминания топиков
            text_elements = message.find_all(text=True)
            for text in text_elements:
                topic_match = re.search(r'топик[_\s]*(\d+)', text, re.IGNORECASE)
                if topic_match:
                    return int(topic_match.group(1))

            # Если топик не найден, используем ID из структуры сообщения
            message_id = self._extract_message_id(message)
            if message_id:
                # Используем хэш от ID сообщения как topic_id для группировки
                return hash(str(message_id)) % 1000000

            return 1  # Дефолтный топик

        except Exception as e:
            logger.error(f"Ошибка извлечения topic_id: {e}")
            return 1

    def _extract_message_id(self, message) -> int:
        """
        Извлекает ID сообщения
        """
        try:
            # Ищем ID в атрибутах сообщения
            if message.get('id'):
                id_match = re.search(r'message-?(\d+)', message.get('id', ''), re.IGNORECASE)
                if id_match:
                    return int(id_match.group(1))

            # Генерируем ID на основе содержания
            text_content = message.get_text()
            return hash(text_content) % 1000000000

        except Exception as e:
            logger.error(f"Ошибка извлечения message_id: {e}")
            return hash(str(datetime.now())) % 1000000000

    def _parse_message(self, message, topic_id: int) -> dict:
        """
        Парсит отдельное сообщение
        """
        try:
            message_data = {
                'message_id': self._extract_message_id(message),
                'topic_id': topic_id,
                'message_text': '',
                'thread_id': None,
                'parent_message_id': None,
                'classification_id': None,
                'created_at': self._extract_message_datetime(message)
            }

            # Извлекаем текст сообщения
            message_text = self._extract_message_text(message)
            if not message_text:
                return None

            message_data['message_text'] = message_text

            # Извлекаем информацию о родительском сообщении (реплай)
            parent_message_id = self._extract_parent_message_id(message)
            if parent_message_id:
                # Проверяем, что родитель НЕ является сервисным сообщением
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
            # Ищем родительское сообщение в DOM
            parent_selector = f'div[id="message-{parent_message_id}"], div[id="message{parent_message_id}"]'
            parent_message = current_message.find_previous_sibling(parent_selector)

            if not parent_message:
                # Если не нашли как предыдущего sibling, ищем по всему документу
                soup = current_message.find_parent()
                if soup:
                    parent_message = soup.find('div', id=re.compile(f'^message-?{parent_message_id}$'))

            if parent_message:
                # Проверяем, является ли родитель сервисным сообщением
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
            # Ищем блок с текстом сообщения - конкретно div с классом "text"
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
            # Ищем элементы реплая
            reply_elements = message.find_all(class_=re.compile(r'reply_to', re.IGNORECASE))
            for element in reply_elements:
                # Ищем ссылки на сообщения
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