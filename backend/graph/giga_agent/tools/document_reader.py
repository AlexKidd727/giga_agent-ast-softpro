"""
Инструменты для чтения документов различных форматов

Поддерживаемые форматы:
- PDF (.pdf) - использует PyPDF2 или pdfplumber
- DOCX (.docx) - использует python-docx
- DOC (.doc) - использует python-docx (требует конвертации) или textract
- RTF (.rtf) - использует striprtf
- TXT (.txt) - читает как обычный текстовый файл
- CSV (.csv) - читает CSV файлы с помощью pandas или csv модуля
- XLS (.xls) - использует xlrd (старый формат Excel)
- XLSX (.xlsx) - использует openpyxl (новый формат Excel)
"""

import os
import logging
from pathlib import Path
from typing import Annotated, Optional

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from pydantic import Field

logger = logging.getLogger(__name__)

# Путь к папке с файлами проекта
FILES_DIR = os.getenv("FILES_DIR", "/files")

# Импортируем утилиты для работы с файлами пользователей
try:
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../repl/app"))
    from user_files_utils import resolve_file_path, get_user_files_dir, normalize_filename
except ImportError:
    # Fallback если модуль недоступен
    def normalize_filename(filename):
        import re
        normalized = re.sub(r'\s+\(', '(', filename)
        normalized = re.sub(r'\(\s+', '(', normalized)
        normalized = re.sub(r'\s+\)', ')', normalized)
        return normalized
    
    def resolve_file_path(file_path, user_id=None):
        # Простой fallback - ищем в общей папке
        clean_path = file_path.lstrip("/")
        potential_paths = [
            os.path.join(FILES_DIR, clean_path),
            file_path,
        ]
        
        # Также пробуем нормализованные варианты
        normalized_path = normalize_filename(clean_path)
        if normalized_path != clean_path:
            potential_paths.append(os.path.join(FILES_DIR, normalized_path))
        
        if user_id:
            filename = os.path.basename(clean_path)
            potential_paths.insert(0, os.path.join(FILES_DIR, user_id, filename))
            normalized_name = normalize_filename(filename)
            if normalized_name != filename:
                potential_paths.insert(0, os.path.join(FILES_DIR, user_id, normalized_name))
        
        for path in potential_paths:
            if os.path.exists(path):
                return Path(path)
        return None
    
    def get_user_files_dir(user_id):
        return Path(FILES_DIR)


@tool(parse_docstring=True)
async def read_document(
    file_path: Annotated[
        str,
        Field(description="Путь к файлу документа для чтения. Может быть локальным путем или URL"),
    ],
    max_pages: Annotated[
        Optional[int],
        Field(
            description="Максимальное количество страниц для чтения (для PDF). Если не указано, читаются все страницы.",
            default=None
        ),
    ] = None,
    max_chars: Annotated[
        Optional[int],
        Field(
            description="Максимальное количество символов для чтения. Если не указано, читается весь файл (до 200000 символов). Для полного чтения больших файлов используйте None или большое значение.",
            default=None
        ),
    ] = None,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """
    Читает содержимое документа различных форматов и возвращает текст.
    
    Поддерживаемые форматы:
    - PDF (.pdf) - использует PyPDF2 или pdfplumber
    - DOCX (.docx) - использует python-docx
    - DOC (.doc) - использует python-docx (требует конвертации) или textract
    - RTF (.rtf) - использует striprtf
    - TXT (.txt) - читает как обычный текстовый файл
    - CSV (.csv) - читает CSV файлы с помощью pandas или csv модуля
    - XLS (.xls) - использует xlrd (старый формат Excel 97-2003)
    - XLSX (.xlsx) - использует openpyxl (новый формат Excel 2007+)
    
    Args:
        file_path: Путь к файлу документа (локальный путь в файловой системе или URL)
        max_pages: Максимальное количество страниц для чтения (только для PDF). Если не указано, читаются все страницы.
        max_chars: Максимальное количество символов для чтения. Если не указано, читается весь файл (до 200000 символов). Для полного чтения больших файлов используйте None или большое значение.
    
    Returns:
        Текст из документа (полный текст для файлов до 200000 символов)
    
    Examples:
        - read_document("resume.pdf")
        - read_document("/files/documents/report.docx")
        - read_document("resume.txt")
        - read_document("data.xlsx")  # Excel файл
        - read_document("old_data.xls")  # Старый формат Excel
        - read_document("large_document.txt", max_chars=100000)  # Ограничить размер
        - read_document("https://example.com/document.pdf", max_pages=10)
    """
    try:
        # Определяем, является ли file_path URL или локальным путем
        is_url = file_path.startswith(("http://", "https://"))
        
        if is_url:
            # Для URL нужно сначала скачать файл
            import aiohttp
            import tempfile
            
            async with aiohttp.ClientSession() as session:
                async with session.get(file_path, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status != 200:
                        return f"Ошибка загрузки файла по URL {file_path}: статус {resp.status}"
                    
                    # Создаем временный файл
                    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file_path).suffix) as tmp_file:
                        tmp_file.write(await resp.read())
                        local_path = tmp_file.name
        else:
            # Локальный путь
            # КРИТИЧЕСКИ ВАЖНО: Получаем user_id из state для поиска файла в папке пользователя
            user_id = None
            if state:
                user_id = state.get("user_id")
                # Нормализуем user_id
                if user_id in ["default_user", "anonymous", "guest", ""]:
                    user_id = None
            
            # Пытаемся найти файл с учетом user_id
            resolved_path = resolve_file_path(file_path, user_id)
            
            if resolved_path and resolved_path.exists():
                local_path = str(resolved_path)
            else:
                # Fallback: проверяем несколько возможных мест с нормализацией
                clean_path = file_path.lstrip("/")
                potential_paths = [
                    file_path,
                    os.path.join(FILES_DIR, clean_path),
                ]
                
                # Пробуем нормализованные варианты
                try:
                    normalized_path = normalize_filename(clean_path)
                    if normalized_path != clean_path:
                        potential_paths.append(os.path.join(FILES_DIR, normalized_path))
                except:
                    pass
                
                # Если путь содержит user_id, пробуем найти в его папке
                if "/" in clean_path:
                    parts = clean_path.split("/", 1)
                    if len(parts) == 2:
                        path_user_id, filename = parts
                        if len(path_user_id) > 20:  # UUID обычно длиннее 20 символов
                            potential_paths.insert(0, os.path.join(FILES_DIR, path_user_id, filename))
                            try:
                                normalized_filename = normalize_filename(filename)
                                if normalized_filename != filename:
                                    potential_paths.insert(0, os.path.join(FILES_DIR, path_user_id, normalized_filename))
                            except:
                                pass
                
                if user_id:
                    filename = os.path.basename(clean_path)
                    potential_paths.insert(0, os.path.join(FILES_DIR, user_id, filename))
                    try:
                        normalized_filename = normalize_filename(filename)
                        if normalized_filename != filename:
                            potential_paths.insert(0, os.path.join(FILES_DIR, user_id, normalized_filename))
                    except:
                        pass
                
                local_path = None
                for path in potential_paths:
                    if os.path.exists(path):
                        local_path = path
                        break
                
                if not local_path or not os.path.exists(local_path):
                    return f"Файл не найден: {file_path}. Проверьте правильность пути."
        
        # Определяем формат файла
        file_ext = Path(local_path).suffix.lower()
        
        # Читаем файл в зависимости от формата
        text = ""
        
        if file_ext == '.pdf':
            text = await _read_pdf(local_path, max_pages)
        elif file_ext == '.docx':
            text = await _read_docx(local_path)
        elif file_ext == '.doc':
            text = await _read_doc(local_path)
        elif file_ext == '.rtf':
            text = await _read_rtf(local_path)
        elif file_ext == '.txt':
            text = await _read_txt(local_path)
        elif file_ext == '.csv':
            text = await _read_csv(local_path)
        elif file_ext == '.xlsx':
            text = await _read_xlsx(local_path)
        elif file_ext == '.xls':
            text = await _read_xls(local_path)
        else:
            return f"Неподдерживаемый формат файла: {file_ext}. Поддерживаются: PDF, DOCX, DOC, RTF, TXT, CSV, XLS, XLSX"
        
        # Удаляем временный файл, если он был создан из URL
        if is_url and os.path.exists(local_path):
            try:
                os.unlink(local_path)
            except Exception as e:
                logger.warning(f"Не удалось удалить временный файл {local_path}: {e}")
        
        if not text:
            return f"Не удалось извлечь текст из файла {file_path}. Возможно, файл поврежден или пуст."
        
        # Ограничиваем размер результата только если указан max_chars или файл очень большой
        if max_chars is not None and len(text) > max_chars:
            text = text[:max_chars] + f"\n\n... (текст обрезан, показаны первые {max_chars} символов из {len(text)})"
        elif max_chars is None and len(text) > 200000:
            # По умолчанию ограничиваем только очень большие файлы (более 200000 символов)
            # Для резюме и обычных документов читаем полностью
            text = text[:200000] + f"\n\n... (текст обрезан, показаны первые 200000 символов из {len(text)})"
        
        return text
        
    except Exception as e:
        error_msg = f"Ошибка при чтении документа {file_path}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return error_msg


async def _read_pdf(file_path: str, max_pages: Optional[int] = None) -> str:
    """Читает PDF файл"""
    try:
        # Пробуем использовать PyPDF2
        try:
            import PyPDF2
            with open(file_path, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                text = ""
                total_pages = len(pdf_reader.pages)
                pages_to_read = min(max_pages, total_pages) if max_pages else total_pages
                
                for i in range(pages_to_read):
                    page = pdf_reader.pages[i]
                    text += page.extract_text() + "\n"
                
                if max_pages and total_pages > max_pages:
                    text += f"\n\n... (показаны первые {max_pages} страниц из {total_pages})"
                
                return text
        except ImportError:
            # Пробуем использовать pdfplumber
            try:
                import pdfplumber
                text = ""
                with pdfplumber.open(file_path) as pdf:
                    total_pages = len(pdf.pages)
                    pages_to_read = min(max_pages, total_pages) if max_pages else total_pages
                    
                    for i in range(pages_to_read):
                        page = pdf.pages[i]
                        text += page.extract_text() or "" + "\n"
                    
                    if max_pages and total_pages > max_pages:
                        text += f"\n\n... (показаны первые {max_pages} страниц из {total_pages})"
                
                return text
            except ImportError:
                return "Ошибка: не установлены библиотеки для чтения PDF. Установите PyPDF2 или pdfplumber."
    except Exception as e:
        logger.error(f"Ошибка чтения PDF {file_path}: {e}")
        return f"Ошибка чтения PDF: {str(e)}"


async def _read_docx(file_path: str) -> str:
    """Читает DOCX файл"""
    try:
        from docx import Document
        doc = Document(file_path)
        text_parts = []
        
        # Читаем параграфы
        for para in doc.paragraphs:
            if para.text.strip():
                text_parts.append(para.text)
        
        # Читаем таблицы
        for table in doc.tables:
            for row in table.rows:
                row_text = []
                for cell in row.cells:
                    if cell.text.strip():
                        row_text.append(cell.text.strip())
                if row_text:
                    text_parts.append(" | ".join(row_text))
        
        return "\n".join(text_parts)
    except ImportError:
        return "Ошибка: не установлена библиотека python-docx. Установите: pip install python-docx"
    except Exception as e:
        logger.error(f"Ошибка чтения DOCX {file_path}: {e}")
        return f"Ошибка чтения DOCX: {str(e)}"


async def _read_doc(file_path: str) -> str:
    """Читает DOC файл (старый формат Word)"""
    try:
        # Пробуем использовать textract (универсальная библиотека)
        try:
            import textract
            text = textract.process(file_path).decode('utf-8')
            return text
        except ImportError:
            # Пробуем использовать python-docx (может не работать для старых DOC)
            try:
                from docx import Document
                # python-docx не поддерживает старые DOC файлы напрямую
                # Пробуем открыть как DOCX (может не сработать)
                doc = Document(file_path)
                text_parts = [para.text for para in doc.paragraphs if para.text.strip()]
                return "\n".join(text_parts)
            except Exception:
                return "Ошибка: для чтения DOC файлов установите textract: pip install textract. Или конвертируйте файл в DOCX."
    except Exception as e:
        logger.error(f"Ошибка чтения DOC {file_path}: {e}")
        return f"Ошибка чтения DOC: {str(e)}"


async def _read_rtf(file_path: str) -> str:
    """Читает RTF файл"""
    try:
        # Пробуем использовать striprtf
        try:
            from striprtf.striprtf import rtf_to_text
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                rtf_content = f.read()
            text = rtf_to_text(rtf_content)
            return text
        except ImportError:
            # Пробуем просто прочитать как текст (RTF содержит текст, но с форматированием)
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            # Простая очистка RTF тегов (базовая)
            import re
            # Удаляем RTF команды
            text = re.sub(r'\\[a-z]+\d*\s?', '', content)
            text = re.sub(r'\{[^}]*\}', '', text)
            return text.strip()
    except Exception as e:
        logger.error(f"Ошибка чтения RTF {file_path}: {e}")
        return f"Ошибка чтения RTF: {str(e)}"


async def _read_txt(file_path: str) -> str:
    """Читает TXT файл"""
    try:
        # Пробуем разные кодировки
        encodings = ['utf-8', 'utf-8-sig', 'cp1251', 'windows-1251', 'latin-1']
        
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    text = f.read()
                    return text
            except UnicodeDecodeError:
                continue
            except Exception as e:
                logger.warning(f"Ошибка чтения TXT с кодировкой {encoding}: {e}")
                continue
        
        # Если все кодировки не подошли, пробуем с обработкой ошибок
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            text = f.read()
            return text
    except Exception as e:
        logger.error(f"Ошибка чтения TXT {file_path}: {e}")
        return f"Ошибка чтения TXT: {str(e)}"


async def _read_csv(file_path: str) -> str:
    """Читает CSV файл"""
    try:
        # Пробуем использовать pandas для чтения CSV
        try:
            import pandas as pd
            # Читаем CSV с автоматическим определением разделителя
            df = pd.read_csv(file_path, encoding='utf-8', on_bad_lines='skip', low_memory=False)
            
            # Форматируем вывод: заголовки и первые строки
            result_parts = []
            
            # Добавляем информацию о структуре
            result_parts.append(f"Структура CSV файла:")
            result_parts.append(f"Количество строк: {len(df)}")
            result_parts.append(f"Количество столбцов: {len(df.columns)}")
            result_parts.append(f"\nСтолбцы: {', '.join(df.columns.tolist())}")
            result_parts.append(f"\nПервые 20 строк данных:")
            result_parts.append("=" * 80)
            
            # Добавляем заголовки
            result_parts.append(" | ".join(df.columns.tolist()))
            result_parts.append("-" * 80)
            
            # Добавляем первые 20 строк
            for idx, row in df.head(20).iterrows():
                row_values = [str(val) if pd.notna(val) else "" for val in row.values]
                result_parts.append(" | ".join(row_values))
            
            if len(df) > 20:
                result_parts.append(f"\n... (показаны первые 20 строк из {len(df)})")
            
            # Добавляем статистику по числовым столбцам
            numeric_cols = df.select_dtypes(include=['number']).columns
            if len(numeric_cols) > 0:
                result_parts.append(f"\nСтатистика по числовым столбцам:")
                result_parts.append(df[numeric_cols].describe().to_string())
            
            return "\n".join(result_parts)
        except ImportError:
            # Fallback: используем стандартный csv модуль
            import csv
            result_parts = []
            encodings = ['utf-8', 'utf-8-sig', 'cp1251', 'windows-1251', 'latin-1']
            
            for encoding in encodings:
                try:
                    with open(file_path, 'r', encoding=encoding, newline='') as f:
                        # Пробуем определить разделитель
                        sample = f.read(1024)
                        f.seek(0)
                        sniffer = csv.Sniffer()
                        delimiter = sniffer.sniff(sample).delimiter
                        
                        reader = csv.reader(f, delimiter=delimiter)
                        rows = list(reader)
                        
                        if not rows:
                            return "CSV файл пуст"
                        
                        # Форматируем вывод
                        result_parts.append(f"Структура CSV файла:")
                        result_parts.append(f"Количество строк: {len(rows)}")
                        result_parts.append(f"Количество столбцов: {len(rows[0])}")
                        result_parts.append(f"\nПервые 20 строк данных:")
                        result_parts.append("=" * 80)
                        
                        for i, row in enumerate(rows[:20]):
                            result_parts.append(" | ".join(str(cell) for cell in row))
                        
                        if len(rows) > 20:
                            result_parts.append(f"\n... (показаны первые 20 строк из {len(rows)})")
                        
                        return "\n".join(result_parts)
                except (UnicodeDecodeError, csv.Error):
                    continue
            
            # Если не удалось прочитать, пробуем как обычный текст
            return await _read_txt(file_path)
    except Exception as e:
        logger.error(f"Ошибка чтения CSV {file_path}: {e}")
        return f"Ошибка чтения CSV: {str(e)}"
        logger.error(f"Ошибка чтения TXT {file_path}: {e}")
        return f"Ошибка чтения TXT: {str(e)}"


async def _read_xlsx(file_path: str) -> str:
    """
    Читает XLSX файл (Excel 2007+, формат Office Open XML).
    Использует библиотеку openpyxl.
    
    Возвращает текстовое представление всех листов таблицы.
    Каждый лист отделен заголовком с названием листа.
    Данные представлены в табличном формате с разделителем |.
    """
    try:
        try:
            from openpyxl import load_workbook
        except ImportError:
            return "Ошибка: не установлена библиотека openpyxl для чтения XLSX файлов. Установите: pip install openpyxl"
        
        # Загружаем книгу (data_only=True для получения значений формул, а не самих формул)
        wb = load_workbook(file_path, data_only=True, read_only=True)
        
        text_parts = []
        
        for sheet_name in wb.sheetnames:
            sheet = wb[sheet_name]
            
            # Добавляем заголовок листа
            text_parts.append(f"\n=== Лист: {sheet_name} ===\n")
            
            rows_data = []
            max_col_widths = {}  # Для выравнивания столбцов
            
            # Собираем данные из всех строк
            for row in sheet.iter_rows():
                row_values = []
                for col_idx, cell in enumerate(row):
                    value = cell.value
                    if value is None:
                        value = ""
                    else:
                        # Преобразуем значение в строку
                        value = str(value).strip()
                    row_values.append(value)
                    
                    # Обновляем максимальную ширину столбца
                    if col_idx not in max_col_widths:
                        max_col_widths[col_idx] = 0
                    max_col_widths[col_idx] = max(max_col_widths[col_idx], len(value))
                
                # Добавляем строку только если она не полностью пустая
                if any(v for v in row_values):
                    rows_data.append(row_values)
            
            # Форматируем строки с выравниванием
            for row_idx, row_values in enumerate(rows_data):
                # Выравниваем значения по ширине столбцов
                formatted_values = []
                for col_idx, value in enumerate(row_values):
                    # Ограничиваем ширину столбца для читаемости
                    max_width = min(max_col_widths.get(col_idx, 0), 50)
                    if len(value) > max_width:
                        value = value[:max_width-3] + "..."
                    formatted_values.append(value.ljust(max_width))
                
                row_text = " | ".join(formatted_values)
                text_parts.append(row_text)
                
                # Добавляем разделитель после заголовка (первой строки)
                if row_idx == 0 and len(rows_data) > 1:
                    separator = "-+-".join("-" * min(max_col_widths.get(i, 0), 50) for i in range(len(row_values)))
                    text_parts.append(separator)
            
            # Добавляем информацию о количестве строк
            text_parts.append(f"\n(Всего строк: {len(rows_data)})")
        
        wb.close()
        
        return "\n".join(text_parts)
        
    except Exception as e:
        logger.error(f"Ошибка чтения XLSX {file_path}: {e}", exc_info=True)
        return f"Ошибка чтения XLSX: {str(e)}"


async def _read_xls(file_path: str) -> str:
    """
    Читает XLS файл (Excel 97-2003, формат BIFF).
    Использует библиотеку xlrd.
    
    Возвращает текстовое представление всех листов таблицы.
    Каждый лист отделен заголовком с названием листа.
    Данные представлены в табличном формате с разделителем |.
    """
    try:
        try:
            import xlrd
        except ImportError:
            return "Ошибка: не установлена библиотека xlrd для чтения XLS файлов. Установите: pip install xlrd"
        
        # Открываем книгу
        wb = xlrd.open_workbook(file_path)
        
        text_parts = []
        
        for sheet_idx in range(wb.nsheets):
            sheet = wb.sheet_by_index(sheet_idx)
            sheet_name = sheet.name
            
            # Добавляем заголовок листа
            text_parts.append(f"\n=== Лист: {sheet_name} ===\n")
            
            rows_data = []
            max_col_widths = {}  # Для выравнивания столбцов
            
            # Собираем данные из всех строк
            for row_idx in range(sheet.nrows):
                row_values = []
                for col_idx in range(sheet.ncols):
                    cell = sheet.cell(row_idx, col_idx)
                    value = cell.value
                    
                    # Обрабатываем разные типы ячеек
                    if cell.ctype == xlrd.XL_CELL_EMPTY:
                        value = ""
                    elif cell.ctype == xlrd.XL_CELL_DATE:
                        # Преобразуем дату Excel в читаемый формат
                        try:
                            date_tuple = xlrd.xldate_as_tuple(value, wb.datemode)
                            if date_tuple[3:] == (0, 0, 0):
                                # Только дата без времени
                                value = f"{date_tuple[2]:02d}.{date_tuple[1]:02d}.{date_tuple[0]}"
                            else:
                                # Дата и время
                                value = f"{date_tuple[2]:02d}.{date_tuple[1]:02d}.{date_tuple[0]} {date_tuple[3]:02d}:{date_tuple[4]:02d}"
                        except Exception:
                            value = str(value)
                    elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                        value = "True" if value else "False"
                    elif cell.ctype == xlrd.XL_CELL_NUMBER:
                        # Форматируем числа: убираем лишние нули после запятой
                        if value == int(value):
                            value = str(int(value))
                        else:
                            value = str(value)
                    else:
                        value = str(value).strip()
                    
                    row_values.append(value)
                    
                    # Обновляем максимальную ширину столбца
                    if col_idx not in max_col_widths:
                        max_col_widths[col_idx] = 0
                    max_col_widths[col_idx] = max(max_col_widths[col_idx], len(value))
                
                # Добавляем строку только если она не полностью пустая
                if any(v for v in row_values):
                    rows_data.append(row_values)
            
            # Форматируем строки с выравниванием
            for row_idx, row_values in enumerate(rows_data):
                # Выравниваем значения по ширине столбцов
                formatted_values = []
                for col_idx, value in enumerate(row_values):
                    # Ограничиваем ширину столбца для читаемости
                    max_width = min(max_col_widths.get(col_idx, 0), 50)
                    if len(value) > max_width:
                        value = value[:max_width-3] + "..."
                    formatted_values.append(value.ljust(max_width))
                
                row_text = " | ".join(formatted_values)
                text_parts.append(row_text)
                
                # Добавляем разделитель после заголовка (первой строки)
                if row_idx == 0 and len(rows_data) > 1:
                    separator = "-+-".join("-" * min(max_col_widths.get(i, 0), 50) for i in range(len(row_values)))
                    text_parts.append(separator)
            
            # Добавляем информацию о количестве строк
            text_parts.append(f"\n(Всего строк: {len(rows_data)})")
        
        return "\n".join(text_parts)
        
    except Exception as e:
        logger.error(f"Ошибка чтения XLS {file_path}: {e}", exc_info=True)
        return f"Ошибка чтения XLS: {str(e)}"

