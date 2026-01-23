/**
 * Утилита для работы с настройками пользователя через API
 * 
 * ВАЖНО: Все настройки хранятся в БД в поле user_preferences таблицы user.
 * Каждый пользователь имеет свои индивидуальные настройки, которые изолированы
 * от настроек других пользователей. API автоматически определяет текущего
 * пользователя по токену аутентификации и возвращает/сохраняет только его настройки.
 */

const API_BASE = "/api";

export interface UserPreferences {
  settings?: {
    autoApprove?: boolean;
    debugMode?: boolean;
    sideBarOpen?: boolean;
    contextInstructions?: string;
    contextSecrets?: Array<any>;
    activeCollections?: Record<string, boolean>;
  };
  mcpServers?: Array<any>;
  mcpServerTools?: Record<string, any>;
  // Базовые предпочтения пользователя (пары ключ-значение)
  // Используются агентом, если в запросе не хватает информации
  basePreferences?: Record<string, string>;
}

/**
 * Загрузить настройки пользователя из БД
 * 
 * ВАЖНО: Возвращает настройки ТОЛЬКО текущего аутентифицированного пользователя.
 * Пользователь определяется автоматически по токену в заголовке Authorization.
 * Другие пользователи не могут получить доступ к чужим настройкам.
 */
export async function loadUserPreferences(
  token: string | null,
): Promise<UserPreferences | null> {
  if (!token) {
    console.warn("[PREFERENCES] loadUserPreferences: токен отсутствует, возвращаем null");
    return null;
  }

  try {
    console.log("[PREFERENCES] loadUserPreferences: начало загрузки, токен существует, длина=", token.length, ", первые 10 символов=", token.substring(0, 10));
    // API endpoint /auth/me/preferences автоматически определяет пользователя по токену
    // и возвращает только его настройки из поля user_preferences
    const response = await fetch(`${API_BASE}/auth/me/preferences`, {
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
    });

    console.log("[PREFERENCES] loadUserPreferences: ответ получен, status=", response.status, ", statusText=", response.statusText);
    
    // Если 401, логируем детали ошибки
    if (response.status === 401) {
      const errorText = await response.text();
      console.error("[PREFERENCES] loadUserPreferences: ошибка 401, детали:", errorText);
      try {
        const errorJson = JSON.parse(errorText);
        console.error("[PREFERENCES] loadUserPreferences: ошибка 401, JSON:", errorJson);
      } catch (e) {
        // Не JSON, уже залогировали как текст
      }
    }

    if (!response.ok) {
      // Если предпочтения еще не установлены, возвращаем null
      if (response.status === 404) {
        console.log("[PREFERENCES] loadUserPreferences: предпочтения не найдены (404)");
        return null;
      }
      console.error("[PREFERENCES] loadUserPreferences: ошибка ответа, status=", response.status);
      throw new Error("Не удалось загрузить настройки");
    }

    const data = await response.json();
    console.log("[PREFERENCES] loadUserPreferences: данные получены, user_preferences exists=", !!data.user_preferences);
    const preferencesJson = data.user_preferences || "";

    if (!preferencesJson.trim()) {
      console.log("[PREFERENCES] loadUserPreferences: предпочтения пустые");
      return null;
    }

    console.log("[PREFERENCES] loadUserPreferences: предпочтения не пустые, длина=", preferencesJson.length, ", первые 200 символов:", preferencesJson.substring(0, 200));

    try {
      const parsed = JSON.parse(preferencesJson);
      console.log("[PREFERENCES] loadUserPreferences: JSON распарсен, тип=", typeof parsed, ", ключи=", parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? Object.keys(parsed) : 'N/A');
      
      // Обработка разных форматов данных
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        // Служебные поля, которые не являются базовыми предпочтениями
        const serviceFields = ['settings', 'mcpServers', 'mcpServerTools', 'basePreferences'];
        
        // Проверяем, есть ли служебные поля (новый формат)
        const hasNewStructure = serviceFields.some(field => field in parsed);
        console.log("[PREFERENCES] loadUserPreferences: hasNewStructure=", hasNewStructure);
        
        // Проверяем, есть ли basePreferences
        const hasBasePreferences = 'basePreferences' in parsed && parsed.basePreferences;
        console.log("[PREFERENCES] loadUserPreferences: hasBasePreferences=", hasBasePreferences);
        
        if (!hasBasePreferences) {
          // basePreferences отсутствует - нужно извлечь базовые предпочтения из корня
          // Фильтруем служебные поля и оставляем только базовые предпочтения
          const basePrefs: Record<string, string> = {};
          Object.keys(parsed).forEach(key => {
            if (!serviceFields.includes(key)) {
              // Это базовое предпочтение - добавляем в basePreferences
              const value = parsed[key];
              if (value !== null && value !== undefined) {
                basePrefs[key] = String(value);
              }
            }
          });
          
          console.log("[PREFERENCES] loadUserPreferences: извлечены базовые предпочтения из корня, количество=", Object.keys(basePrefs).length, ", ключи=", Object.keys(basePrefs));
          
          // Создаем правильную структуру с basePreferences
          // Сохраняем служебные поля и добавляем basePreferences
          const result: UserPreferences = {
            settings: parsed.settings || {},
            mcpServers: parsed.mcpServers || [],
            mcpServerTools: parsed.mcpServerTools || {},
            basePreferences: basePrefs,
          };
          
          console.log("[PREFERENCES] loadUserPreferences: результат преобразования, basePreferences keys=", Object.keys(result.basePreferences || {}), ", остальные ключи=", Object.keys(result).filter(k => k !== 'basePreferences'));
          return result;
        } else {
          console.log("[PREFERENCES] loadUserPreferences: новый формат с basePreferences, basePreferences keys=", parsed.basePreferences ? Object.keys(parsed.basePreferences) : 'N/A');
        }
      }
      
      console.log("[PREFERENCES] loadUserPreferences: возвращаем распарсенные предпочтения");
      return parsed as UserPreferences;
    } catch (e) {
      console.error("[PREFERENCES] loadUserPreferences: ошибка парсинга настроек из БД:", e);
      return null;
    }
  } catch (error) {
    console.error("[PREFERENCES] loadUserPreferences: ошибка загрузки настроек:", error);
    return null;
  }
}

/**
 * Сохранить настройки пользователя в БД
 * 
 * ВАЖНО: Сохраняет настройки ТОЛЬКО для текущего аутентифицированного пользователя.
 * Пользователь определяется автоматически по токену в заголовке Authorization.
 * Настройки сохраняются в поле user_preferences таблицы user для конкретного пользователя.
 * Другие пользователи не могут изменить чужие настройки.
 */
export async function saveUserPreferences(
  token: string | null,
  preferences: UserPreferences,
): Promise<boolean> {
  if (!token) {
    console.warn("Не удалось сохранить настройки: токен отсутствует");
    return false;
  }

  try {
    const preferencesJson = JSON.stringify(preferences);

    // API endpoint /auth/me/preferences автоматически определяет пользователя по токену
    // и сохраняет настройки только в его запись в БД
    const response = await fetch(`${API_BASE}/auth/me/preferences`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        user_preferences: preferencesJson,
      }),
    });

    if (!response.ok) {
      throw new Error("Не удалось сохранить настройки");
    }

    return true;
  } catch (error) {
    console.error("Ошибка сохранения настроек:", error);
    return false;
  }
}

/**
 * Обновить часть настроек (merge с существующими)
 */
export async function updateUserPreferences(
  token: string | null,
  updates: Partial<UserPreferences>,
): Promise<boolean> {
  if (!token) {
    return false;
  }

  // Загружаем текущие настройки
  const current = await loadUserPreferences(token);
  
  // Мержим с обновлениями
  const merged: UserPreferences = {
    ...current,
    ...updates,
    settings: {
      ...current?.settings,
      ...updates.settings,
    },
    mcpServers: updates.mcpServers !== undefined 
      ? updates.mcpServers 
      : current?.mcpServers,
    mcpServerTools: {
      ...current?.mcpServerTools,
      ...updates.mcpServerTools,
    },
    basePreferences: updates.basePreferences !== undefined
      ? updates.basePreferences
      : current?.basePreferences,
  };

  return await saveUserPreferences(token, merged);
}

