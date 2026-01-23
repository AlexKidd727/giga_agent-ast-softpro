"""
Асинхронный клиент для работы с SMTP
"""

import asyncio
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import Optional, List, Dict
import logging

logger = logging.getLogger(__name__)


class SMTPClient:
    """Асинхронный клиент для работы с SMTP сервером"""
    
    def __init__(self, host: str, port: int, email: str, password: str, use_tls: bool = True):
        """
        Инициализация SMTP клиента
        
        Args:
            host: SMTP сервер
            port: Порт SMTP сервера
            email: Email адрес
            password: Пароль
            use_tls: Использовать TLS (по умолчанию True)
        """
        logger.info(f"[SMTP_CLIENT] SMTPClient.__init__: host={host}, port={port}, email={email}, use_tls={use_tls}, password={'***' if password else None}")
        self.host = host
        self.port = port
        self.email = email
        self.password = password
        self.use_tls = use_tls
        self.smtp: Optional[smtplib.SMTP] = None
    
    async def connect(self) -> bool:
        """
        Подключение к SMTP серверу
        
        Returns:
            True если подключение успешно
        """
        logger.info(f"[SMTP_CLIENT] connect: начинаем подключение к SMTP: host={self.host}, port={self.port}, email={self.email}")
        try:
            loop = asyncio.get_event_loop()
            logger.info(f"[SMTP_CLIENT] connect: создаем SMTP соединение с {self.host}:{self.port}")
            self.smtp = await loop.run_in_executor(
                None,
                lambda: smtplib.SMTP(self.host, self.port)
            )
            
            if self.use_tls:
                logger.info(f"[SMTP_CLIENT] connect: включаем TLS")
                await loop.run_in_executor(
                    None,
                    lambda: self.smtp.starttls()
                )
            
            logger.info(f"[SMTP_CLIENT] connect: выполняем login для {self.email}")
            await loop.run_in_executor(
                None,
                lambda: self.smtp.login(self.email, self.password)
            )
            
            logger.info(f"[SMTP_CLIENT] connect: УСПЕШНО подключились к SMTP для {self.email} на {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"[SMTP_CLIENT] connect: ОШИБКА подключения к SMTP для {self.email} на {self.host}:{self.port}: {e}", exc_info=True)
            return False
    
    async def disconnect(self):
        """Отключение от SMTP сервера"""
        if self.smtp:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self.smtp.quit)
            except Exception as e:
                logger.warning(f"Ошибка при отключении от SMTP: {e}")
            finally:
                self.smtp = None
    
    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        cc: Optional[List[str]] = None,
        attachments: Optional[List[Dict]] = None
    ) -> bool:
        """
        Отправка письма
        
        Args:
            to: Email получателя
            subject: Тема письма
            body: Текст письма
            html_body: HTML версия письма (опционально)
            cc: Список получателей копии (опционально)
            attachments: Список вложений (опционально)
                Формат: [{"filename": "file.txt", "data": bytes, "content_type": "text/plain"}]
        
        Returns:
            True если письмо отправлено успешно
        """
        if not self.smtp:
            if not await self.connect():
                return False
        
        try:
            # Создаем сообщение
            if html_body or attachments:
                msg = MIMEMultipart('alternative')
            else:
                msg = MIMEText(body, 'plain', 'utf-8')
            
            msg['From'] = self.email
            msg['To'] = to
            msg['Subject'] = subject
            
            if cc:
                msg['Cc'] = ', '.join(cc)
            
            # Добавляем текстовую версию
            if html_body or attachments:
                part1 = MIMEText(body, 'plain', 'utf-8')
                msg.attach(part1)
            
            # Добавляем HTML версию
            if html_body:
                part2 = MIMEText(html_body, 'html', 'utf-8')
                msg.attach(part2)
            
            # Добавляем вложения
            if attachments:
                for attachment in attachments:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(attachment['data'])
                    encoders.encode_base64(part)
                    part.add_header(
                        'Content-Disposition',
                        f'attachment; filename= {attachment["filename"]}'
                    )
                    msg.attach(part)
            
            # Отправляем
            recipients = [to]
            if cc:
                recipients.extend(cc)
            
            loop = asyncio.get_event_loop()
            # Отправляем письмо и получаем результат
            failed_recipients = await loop.run_in_executor(
                None,
                lambda: self.smtp.sendmail(self.email, recipients, msg.as_string())
            )
            
            # sendmail возвращает словарь с неудачными получателями (пустой словарь = успех)
            if failed_recipients:
                logger.error(f"Ошибка отправки письма: не удалось отправить некоторым получателям: {failed_recipients}")
                return False
            
            logger.info(f"Письмо успешно отправлено от {self.email} к {to}")
            return True
        except smtplib.SMTPException as e:
            logger.error(f"SMTP ошибка отправки письма: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Ошибка отправки письма: {e}", exc_info=True)
            return False
    
    async def reply_to_email(
        self,
        original_msg: Dict,
        body: str,
        html_body: Optional[str] = None,
        attachments: Optional[List[Dict]] = None
    ) -> bool:
        """
        Ответ на письмо
        
        Args:
            original_msg: Информация об оригинальном письме
            body: Текст ответа
            html_body: HTML версия ответа (опционально)
            attachments: Список вложений (опционально)
        
        Returns:
            True если ответ отправлен успешно
        """
        # Формируем тему ответа
        original_subject = original_msg.get('subject', '')
        if not original_subject.startswith('Re:'):
            subject = f"Re: {original_subject}"
        else:
            subject = original_subject
        
        # Получаем адрес отправителя оригинального письма
        from_addr = original_msg.get('from', '')
        # Извлекаем email из строки "Name <email@example.com>"
        if '<' in from_addr and '>' in from_addr:
            to = from_addr.split('<')[1].split('>')[0]
        else:
            to = from_addr.strip()
        
        return await self.send_email(
            to=to,
            subject=subject,
            body=body,
            html_body=html_body,
            attachments=attachments
        )
    
    async def __aenter__(self):
        """Поддержка async context manager"""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Поддержка async context manager"""
        await self.disconnect()

