/**
 * Утилита для работы с Redis API
 * Прямые обращения из фронтенда для обновления user_id в Redis
 */

const API_BASE = "/api";

interface RedisSessionResponse {
  success: boolean;
  message: string;
  user_id?: string;
  thread_id?: string;
}

/**
 * Создать сеанс пользователя в Redis
 * Вызывается при авторизации ДО создания потока
 */
export async function createRedisSession(token: string): Promise<RedisSessionResponse> {
  try {
    const url = `${API_BASE}/redis/session/create`;
    console.log(`🔍 Redis API: Создание сеанса, URL: ${url}`);
    
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
    });

    console.log(`🔍 Redis API: Ответ получен, статус: ${response.status}`);

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Неизвестная ошибка" }));
      console.error(`❌ Redis API: Ошибка создания сеанса (${response.status}):`, error);
      throw new Error(error.detail || "Не удалось создать сеанс в Redis");
    }

    const data = await response.json();
    console.log(`✅ Redis API: Сеанс создан успешно:`, data);
    return data;
  } catch (error) {
    console.error("❌ Ошибка при создании сеанса в Redis:", error);
    throw error;
  }
}

/**
 * Добавить thread_id в сеанс пользователя в Redis
 * Вызывается при создании потока
 */
export async function addThreadToRedisSession(
  threadId: string,
  token: string
): Promise<RedisSessionResponse> {
  try {
    const url = `${API_BASE}/redis/thread/${threadId}`;
    console.log(`🔍 Redis API: Добавление thread_id в сеанс, URL: ${url}, threadId: ${threadId}`);
    
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
    });

    console.log(`🔍 Redis API: Ответ получен, статус: ${response.status}`);

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Неизвестная ошибка" }));
      console.error(`❌ Redis API: Ошибка добавления thread_id (${response.status}):`, error);
      throw new Error(error.detail || "Не удалось добавить thread_id в сеанс");
    }

    const data = await response.json();
    console.log(`✅ Redis API: thread_id добавлен успешно:`, data);
    return data;
  } catch (error) {
    console.error("❌ Ошибка при добавлении thread_id в сеанс Redis:", error);
    throw error;
  }
}

