import { useState, useEffect, useCallback } from "react";
import { useAuth } from "@/components/Auth/AuthContext";

export interface SavedChat {
  threadId: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  firstMessage?: string;
}

const STORAGE_KEY = "giga_agent_chat_history";
const MAX_CHATS = 50; // Максимальное количество сохраненных чатов

export function useChatHistory() {
  const { user } = useAuth();
  const [chats, setChats] = useState<SavedChat[]>([]);

  // Загрузка чатов из localStorage при инициализации и при смене пользователя
  useEffect(() => {
    if (!user) {
      // Если пользователь не авторизован, очищаем чаты
      setChats([]);
      return;
    }
    
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored) as SavedChat[];
        // Сортируем по дате обновления (новые сверху)
        const sorted = parsed.sort((a, b) => b.updatedAt - a.updatedAt);
        setChats(sorted);
      } else {
        setChats([]);
      }
    } catch (error) {
      console.error("Ошибка при загрузке истории чатов:", error);
      setChats([]);
    }
  }, [user]);

  // Сохранение чатов в localStorage
  const saveChats = useCallback((newChats: SavedChat[]) => {
    try {
      // Ограничиваем количество чатов
      const limited = newChats.slice(0, MAX_CHATS);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(limited));
      // Не обновляем состояние здесь, так как оно уже обновлено в saveChat
    } catch (error) {
      console.error("Ошибка при сохранении истории чатов:", error);
    }
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
    (threadId: string, firstMessage?: string, customTitle?: string) => {
      setChats((prevChats) => {
        const existingIndex = prevChats.findIndex(
          (chat) => chat.threadId === threadId,
        );

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

        const now = Date.now();

        let newChats: SavedChat[];
        if (existingIndex >= 0) {
          // Обновляем существующий чат
          newChats = [...prevChats];
          newChats[existingIndex] = {
            ...newChats[existingIndex],
            title,
            updatedAt: now,
            firstMessage: firstMessage || newChats[existingIndex].firstMessage,
          };
        } else {
          // Добавляем новый чат
          const newChat: SavedChat = {
            threadId,
            title,
            createdAt: now,
            updatedAt: now,
            firstMessage,
          };
          newChats = [newChat, ...prevChats];
        }

        // Сортируем по дате обновления
        newChats.sort((a, b) => b.updatedAt - a.updatedAt);
        
        // Сохраняем в localStorage
        try {
          const limited = newChats.slice(0, MAX_CHATS);
          localStorage.setItem(STORAGE_KEY, JSON.stringify(limited));
        } catch (error) {
          console.error("Ошибка при сохранении истории чатов:", error);
        }
        
        // Возвращаем новый массив для гарантии обновления React
        return newChats.slice(0, MAX_CHATS);
      });
    },
    [],
  );

  // Удаление чата
  const deleteChat = useCallback(
    (threadId: string) => {
      setChats((prevChats) => {
        const newChats = prevChats.filter((chat) => chat.threadId !== threadId);
        // Сохраняем в localStorage
        try {
          const limited = newChats.slice(0, MAX_CHATS);
          localStorage.setItem(STORAGE_KEY, JSON.stringify(limited));
        } catch (error) {
          console.error("Ошибка при сохранении истории чатов:", error);
        }
        return newChats.slice(0, MAX_CHATS);
      });
    },
    [],
  );

  // Обновление заголовка чата
  const updateChatTitle = useCallback(
    (threadId: string, title: string) => {
      setChats((prevChats) => {
        const newChats = prevChats.map((chat) =>
          chat.threadId === threadId
            ? { ...chat, title, updatedAt: Date.now() }
            : chat,
        );
        newChats.sort((a, b) => b.updatedAt - a.updatedAt);
        // Сохраняем в localStorage
        try {
          const limited = newChats.slice(0, MAX_CHATS);
          localStorage.setItem(STORAGE_KEY, JSON.stringify(limited));
        } catch (error) {
          console.error("Ошибка при сохранении истории чатов:", error);
        }
        return newChats.slice(0, MAX_CHATS);
      });
    },
    [],
  );

  // Очистка всей истории
  const clearHistory = useCallback(() => {
    try {
      localStorage.removeItem(STORAGE_KEY);
      setChats([]);
    } catch (error) {
      console.error("Ошибка при очистке истории чатов:", error);
    }
  }, []);

  return {
    chats,
    saveChat,
    deleteChat,
    updateChatTitle,
    clearHistory,
  };
}

