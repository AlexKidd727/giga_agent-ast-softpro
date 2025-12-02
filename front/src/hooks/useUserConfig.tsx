/**
 * Хук для автоматической передачи user_id во все запросы к графу
 * Гарантирует, что user_id всегда передается, даже при переподключении
 * 
 * РЕШЕНИЕ ПРОБЛЕМЫ ПОТЕРИ user_id:
 * - Централизованное управление передачей user_id
 * - Автоматическая проверка состояния аутентификации
 * - Гарантированная передача user_id во все запросы
 */
import { useMemo } from "react";
import { useAuth } from "../components/Auth/AuthContext";

export interface UserConfig {
  user_id: string;
}

/**
 * Возвращает configurable объект с user_id для передачи в useStream и submit
 * 
 * ВАЖНО: Всегда возвращает объект с user_id, если пользователь аутентифицирован.
 * Возвращает undefined только если пользователь еще загружается или не аутентифицирован.
 * 
 * Это гарантирует, что user_id не будет потерян при переподключении или обновлении компонента.
 */
export function useUserConfig(): { configurable?: UserConfig } | undefined {
  const { user, loading, isAuthenticated } = useAuth();

  return useMemo(() => {
    // Если еще загружается, возвращаем undefined (не блокируем, но и не передаем невалидные данные)
    if (loading) {
      console.debug("⏳ useUserConfig: Ожидание загрузки пользователя...");
      return undefined;
    }

    // Если пользователь не аутентифицирован, возвращаем undefined
    if (!isAuthenticated || !user?.user_id) {
      console.warn("⚠️ useUserConfig: Пользователь не аутентифицирован или user_id отсутствует");
      return undefined;
    }

    // ВАЖНО: Всегда возвращаем объект с user_id - это гарантирует его передачу
    // Проверяем, что user_id валидный (не пустая строка и не 'anonymous')
    const userId = user.user_id?.trim();
    if (!userId || userId.toLowerCase() === 'anonymous') {
      console.error(`❌ useUserConfig: Невалидный user_id: '${userId}'`);
      return undefined;
    }

    const config = {
      configurable: {
        user_id: userId,
      },
    };
    
    console.debug(`✅ useUserConfig: user_id готов для передачи: ${userId}`);
    return config;
  }, [user?.user_id, loading, isAuthenticated]);
}

/**
 * Возвращает только user_id для использования в других местах
 * 
 * @returns user_id если пользователь аутентифицирован, иначе undefined
 */
export function useUserId(): string | undefined {
  const { user, isAuthenticated } = useAuth();
  
  if (!isAuthenticated || !user?.user_id) {
    return undefined;
  }
  
  return user.user_id;
}

