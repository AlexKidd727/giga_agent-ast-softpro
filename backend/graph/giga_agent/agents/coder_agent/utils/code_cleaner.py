"""
Утилиты для очистки сгенерированного кода
"""

import re


def clean_generated_code(code: str, file_path: str) -> str:
    """
    Очищает сгенерированный код от markdown разметки, лишних элементов и дублирующегося кода
    """
    if not code:
        return ''
    
    # Убираем блоки кода ```language ... ```
    code = re.sub(r'```[\w]*\n?', '', code)
    code = re.sub(r'```', '', code)
    
    # Убираем markdown заголовки в начале
    lines = code.split('\n')
    cleaned_lines = []
    skip_headers = True
    for line in lines:
        if skip_headers:
            if line.strip().startswith('#') or (not line.strip()):
                continue
            skip_headers = False
        cleaned_lines.append(line)
    
    code = '\n'.join(cleaned_lines).strip()
    
    # Убираем комментарии о модели/дате в начале файла
    if 'модель:' in code.lower() or 'model:' in code.lower():
        lines = code.split('\n')
        cleaned = []
        for line in lines:
            if any(x in line.lower() for x in ['модель:', 'model:', 'дата:', 'date:', 'сгенерировано:', 'generated:']):
                continue
            cleaned.append(line)
        code = '\n'.join(cleaned).strip()
    
    # Проверяем на дублирование кода
    if len(code) > 100:
        lines = code.split('\n')
        total_lines = len(lines)
        
        if total_lines > 10:
            first_half_lines = total_lines // 2
            first_half = '\n'.join(lines[:first_half_lines])
            
            second_half_start = total_lines - first_half_lines
            second_half = '\n'.join(lines[second_half_start:])
            
            if first_half_lines > 5:
                first_sample = '\n'.join(lines[:min(10, first_half_lines)])
                second_sample_lines = lines[second_half_start:second_half_start + min(10, len(lines) - second_half_start)]
                second_sample = '\n'.join(second_sample_lines)
                
                if first_sample and second_sample:
                    first_end = '\n'.join(lines[first_half_lines - 5:first_half_lines])
                    second_start = '\n'.join(lines[second_half_start:second_half_start + 5])
                    
                    first_end_norm = first_end.lower().strip()
                    second_start_norm = second_start.lower().strip()
                    
                    if first_end_norm and second_start_norm:
                        similarity = 0
                        min_len = min(len(first_end_norm), len(second_start_norm))
                        if min_len > 0:
                            matches = sum(1 for i in range(min_len) if first_end_norm[i] == second_start_norm[i])
                            similarity = matches / min_len
                        
                        if similarity > 0.9:
                            print(f"[CODER AGENT] ⚠️ Обнаружено дублирование блока в {file_path}")
                            code = '\n'.join(lines[:first_half_lines])
    
    # Специальная обработка для requirements.txt
    if file_path.lower().endswith('requirements.txt'):
        lines = code.split('\n')
        cleaned_requirements = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('```') or line.startswith('*'):
                continue
            if line.startswith('##') or line.startswith('#'):
                continue
            if any(x in line.lower() for x in ['requirements.txt', 'зависимости', 'dependencies', 'этот файл', 'this file']):
                continue
            if '==' in line or '>=' in line or '<=' in line or '>' in line or '<' in line or '~=' in line:
                cleaned_requirements.append(line)
            elif line and not any(x in line for x in ['http://', 'https://', 'git+', 'file://']):
                cleaned_requirements.append(line)
        code = '\n'.join(cleaned_requirements)
    
    return code

