import { useState, useEffect, useCallback } from "react";
import { useAuth } from "@/components/Auth/AuthContext";

export interface SavedChat {
  threadId: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  firstMessage?: string;
}

const API_BASE = "/api";
const MAX_CHATS = 50; // Максимальное количество сохраненных чатов

export function useChatHistory() {
  const { user, token } = useAuth();
  const [chats, setChats] = useState<SavedChat[]>([]);
  const [loading, setLoading] = useState(false);

  // Функция загрузки чатов с сервера
  const loadChats = useCallback(async () => {
    if (!user || !token) {
      console.log("⚠️ loadChats: пользователь или токен отсутствуют, очищаем список");
      setChats([]);
      return;
    }

    console.log(`🔄 loadChats: начинаем загрузку для пользователя ${user.username} (${user.user_id})`);
    setLoading(true);
    try {
      const response = await fetch(`${API_BASE}/chats/`, {
        headers: {
          "Authorization": `Bearer ${token}`,
          "Content-Type": "application/json",
        },
      });

      if (!response.ok) {
        const errorText = await response.text();
        console.error(`❌ loadChats: ошибка HTTP ${response.status}: ${errorText}`);
        throw new Error(`Ошибка загрузки чатов: ${response.status}`);
      }

      const serverChats = await response.json();
      console.log(`📥 loadChats: получено ${serverChats.length} чатов с сервера`);
      
      // Преобразуем формат с сервера в формат для клиента
      const formattedChats: SavedChat[] = serverChats.map((chat: any) => ({
        threadId: chat.thread_id,
        title: chat.title,
        createdAt: new Date(chat.created_at).getTime(),
        updatedAt: new Date(chat.updated_at).getTime(),
        firstMessage: chat.first_message || undefined,
      }));

      // Сортируем по дате обновления (новые сверху)
      const sorted = formattedChats.sort((a, b) => b.updatedAt - a.updatedAt);
      setChats(sorted);
      console.log(`✅ Список чатов загружен: ${sorted.length} чатов`);
      if (sorted.length > 0) {
        console.log(`📋 Первые чаты:`, sorted.slice(0, 3).map(c => ({ threadId: c.threadId, title: c.title })));
      }
    } catch (error) {
      console.error("❌ Ошибка при загрузке истории чатов:", error);
      console.error("   Детали ошибки:", error instanceof Error ? error.message : String(error));
      // Не очищаем список при ошибке, чтобы не потерять уже загруженные чаты
      // setChats([]);
    } finally {
      setLoading(false);
    }
  }, [user, token]);

  // Загрузка чатов с сервера при инициализации и при смене пользователя
  useEffect(() => {
    // Загружаем чаты только если пользователь авторизован
    if (user && token) {
      console.log(`🔄 Загрузка чатов для пользователя: ${user.username} (${user.user_id})`);
      loadChats();
    } else {
      // Очищаем список чатов при выходе пользователя
      console.log(`🔄 Пользователь не авторизован, очищаем список чатов`);
      setChats([]);
    }
  }, [user, token, loadChats]); // Добавляем loadChats в зависимости для правильной работы

  // Сохранение чатов на сервер (не используется напрямую, но оставляем для совместимости)
  const saveChats = useCallback((_newChats: SavedChat[]) => {
    // Эта функция больше не используется, так как чаты сохраняются на сервере
    // Оставляем для обратной совместимости
    console.warn("saveChats больше не используется, чаты сохраняются на сервере");
  }, []);

  // Функция для очистки тегов из текста
  const cleanMessage = (text: string): string => {
    // Убираем теги <task> и </task>
    let cleaned = text.replace(/<task>/gi, "").replace(/<\/task>/gi, "");
    // Убираем лишние пробелы
    cleaned = cleaned.trim();
    return cleaned;
  };

  // Добавление или обновление чата
  const saveChat = useCallback(
    async (threadId: string, firstMessage?: string, customTitle?: string) => {
      if (!user || !token) {
        console.warn("Пользователь не авторизован, чат не сохранен");
        return;
      }

      let title: string;
      if (customTitle && customTitle.trim()) {
        // Используем переданное название
        title = customTitle.trim().slice(0, 100);
      } else if (firstMessage && firstMessage.trim()) {
        // Очищаем сообщение от тегов и используем как название
        const cleaned = cleanMessage(firstMessage);
        title = cleaned.slice(0, 100) || `Чат ${new Date().toLocaleDateString("ru-RU")}`;
      } else {
        title = `Чат ${new Date().toLocaleDateString("ru-RU")}`;
      }

      // Оптимистичное обновление: сразу добавляем чат в список для мгновенной обратной связи
      const now = Date.now();
      const optimisticChat: SavedChat = {
        threadId: threadId,
        title: title,
        createdAt: now,
        updatedAt: now,
        firstMessage: firstMessage || undefined,
      };

      // Добавляем чат в список сразу (оптимистично)
      setChats((prevChats) => {
        const existingIndex = prevChats.findIndex(
          (chat) => chat.threadId === threadId,
        );

        if (existingIndex >= 0) {
          // Обновляем существующий чат
          const newChats = [...prevChats];
          newChats[existingIndex] = optimisticChat;
          return newChats.sort((a, b) => b.updatedAt - a.updatedAt).slice(0, MAX_CHATS);
        } else {
          // Добавляем новый чат в начало списка
          const newChats = [optimisticChat, ...prevChats];
          return newChats.sort((a, b) => b.updatedAt - a.updatedAt).slice(0, MAX_CHATS);
        }
      });

      console.log(`✅ Чат добавлен в список оптимистично: ${threadId}, название: ${title}`);

      try {
        const response = await fetch(`${API_BASE}/chats/`, {
          method: "POST",
          headers: {
            "Authorization": `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            thread_id: threadId,
            title: title,
            first_message: firstMessage || null,
          }),
        });

        if (!response.ok) {
          throw new Error(`Ошибка сохранения чата: ${response.status}`);
        }

        const savedChat = await response.json();
        console.log(`✅ Чат сохранен на сервере: ${savedChat.thread_id}, название: ${savedChat.title}`);
        
        // Обновляем оптимистично добавленный чат данными с сервера
        setChats((prevChats) => {
          const existingIndex = prevChats.findIndex(
            (chat) => chat.threadId === threadId,
          );

          const formattedChat: SavedChat = {
            threadId: savedChat.thread_id,
            title: savedChat.title,
            createdAt: new Date(savedChat.created_at).getTime(),
            updatedAt: new Date(savedChat.updated_at).getTime(),
            firstMessage: savedChat.first_message || undefined,
          };

          let newChats: SavedChat[];
          if (existingIndex >= 0) {
            // Обновляем существующий чат данными с сервера
            newChats = [...prevChats];
            newChats[existingIndex] = formattedChat;
          } else {
            // Добавляем новый чат в начало списка (если его еще нет)
            newChats = [formattedChat, ...prevChats];
          }

          // Сортируем по дате обновления (новые сверху)
          newChats.sort((a, b) => b.updatedAt - a.updatedAt);
          
          // Ограничиваем количество чатов
          return newChats.slice(0, MAX_CHATS);
        });
        
        // Принудительно перезагружаем список чатов с сервера для полной синхронизации
        // Это гарантирует, что список всегда актуален и содержит все сохраненные чаты
        console.log(`🔄 Перезагружаем список чатов с сервера...`);
        await loadChats();
        console.log(`✅ Список чатов перезагружен после сохранения`);
      } catch (error) {
        console.error("Ошибка при сохранении чата:", error);
        // В случае ошибки перезагружаем список, чтобы убрать оптимистично добавленный чат, если он не сохранился
        await loadChats();
      }
    },
    [user, token, loadChats],
  );

  // Удаление чата
  const deleteChat = useCallback(
    async (threadId: string) => {
      if (!user || !token) {
        console.warn("Пользователь не авторизован, чат не удален");
        return;
      }

      try {
        const response = await fetch(`${API_BASE}/chats/${threadId}/`, {
          method: "DELETE",
          headers: {
            "Authorization": `Bearer ${token}`,
            "Content-Type": "application/json",
          },
        });

        if (!response.ok && response.status !== 204) {
          throw new Error(`Ошибка удаления чата: ${response.status}`);
        }

        // Обновляем локальное состояние
        setChats((prevChats) => {
          return prevChats.filter((chat) => chat.threadId !== threadId);
        });
        
        // Принудительно перезагружаем список чатов с сервера для синхронизации
        await loadChats();
      } catch (error) {
        console.error("Ошибка при удалении чата:", error);
        // В случае ошибки все равно пытаемся перезагрузить список
        await loadChats();
      }
    },
    [user, token, loadChats],
  );

  // Обновление заголовка чата
  const updateChatTitle = useCallback(
    async (threadId: string, title: string) => {
      if (!user || !token) {
        console.warn("Пользователь не авторизован, заголовок не обновлен");
        return;
      }

      try {
        const response = await fetch(`${API_BASE}/chats/${threadId}/`, {
          method: "PUT",
          headers: {
            "Authorization": `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            title: title.trim().slice(0, 100),
          }),
        });

        if (!response.ok) {
          throw new Error(`Ошибка обновления чата: ${response.status}`);
        }

        const updatedChat = await response.json();
        
        // Обновляем локальное состояние
        setChats((prevChats) => {
          const newChats = prevChats.map((chat) =>
            chat.threadId === threadId
              ? {
                  ...chat,
                  title: updatedChat.title,
                  updatedAt: new Date(updatedChat.updated_at).getTime(),
                }
              : chat,
          );
          newChats.sort((a, b) => b.updatedAt - a.updatedAt);
          return newChats;
        });
        
        // Принудительно перезагружаем список чатов с сервера для синхронизации
        await loadChats();
      } catch (error) {
        console.error("Ошибка при обновлении заголовка чата:", error);
        // В случае ошибки все равно пытаемся перезагрузить список
        await loadChats();
      }
    },
    [user, token, loadChats],
  );

  // Очистка всей истории
  const clearHistory = useCallback(async () => {
    if (!user || !token) {
      console.warn("Пользователь не авторизован, история не очищена");
      return;
    }

    try {
      // Удаляем все чаты по одному
      const chatsToDelete = [...chats];
      for (const chat of chatsToDelete) {
        await deleteChat(chat.threadId);
      }
      setChats([]);
    } catch (error) {
      console.error("Ошибка при очистке истории чатов:", error);
    }
  }, [user, token, chats, deleteChat]);

  return {
    chats,
    saveChat,
    deleteChat,
    updateChatTitle,
    clearHistory,
    loading,
    refreshChats: loadChats, // Экспортируем функцию для принудительной перезагрузки
  };
}

