import React, { useCallback, useEffect, useState, useMemo, useRef } from "react";
import MessageList from "./MessageList";
import InputArea from "./InputArea";
import { useStream } from "@langchain/langgraph-sdk/react";
import { useStableMessages } from "../hooks/useStableMessages";
import { GraphState } from "../interfaces";
import { useNavigate, useParams } from "react-router-dom";
import { uiMessageReducer } from "@langchain/langgraph-sdk/react-ui";
import { SelectedAttachmentsProvider } from "../hooks/SelectedAttachmentsContext.tsx";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { useChatHistory } from "../hooks/useChatHistory";
import { Message } from "@langchain/langgraph-sdk";
import { useAuth } from "./Auth/AuthContext";
import { useUserConfig } from "../hooks/useUserConfig";
import { useSettings } from "./Settings.tsx";
import { addThreadToRedisSession } from "../utils/redisApi";
import DebugMessage from "./DebugMessage";
import { useSettingsData } from "./Settings/SettingsDataContext";
import ChatModelInfo from "./ChatModelInfo";
import { Printer } from "lucide-react";

interface ChatProps {
  onThreadIdChange?: (threadId: string) => void;
  onThreadReady?: (thread: UseStream<GraphState>) => void;
}

const Chat: React.FC<ChatProps> = ({ onThreadIdChange, onThreadReady }) => {
  const navigate = useNavigate();
  const { threadId } = useParams<{ threadId?: string }>();
  const { saveChat, refreshChats } = useChatHistory();
  const [currentThreadId, setCurrentThreadId] = useState<string | null>(null);
  const [debugMessages, setDebugMessages] = useState<Array<{ id: string; message: string; type: "info" | "success" | "warning" | "error" }>>([]);
  const { user, loading, isAuthenticated, token } = useAuth();
  const userConfig = useUserConfig();
  const { settings } = useSettings();
  // Используем useSettingsData - провайдер должен быть доступен на уровне App
  const { loadSettings } = useSettingsData();
  // Ref для хранения первого сообщения при создании нового чата
  const pendingFirstMessageRef = useRef<string | null>(null);

  // ВАЖНО: configurable должен всегда содержать user_id для всех запросов
  // Используем централизованный хук для гарантированной передачи user_id
  // Убеждаемся, что configurable всегда передается, даже если userConfig еще загружается
  // Это предотвращает установку 'anonymous' по умолчанию
  const threadConfig = useMemo(() => {
    // Если userConfig готов, используем его
    if (userConfig?.configurable?.user_id) {
      return {
        configurable: userConfig.configurable,
      };
    }
    
    // Если пользователь загружается, возвращаем undefined (поток не создастся)
    if (loading) {
      return undefined;
    }
    
    // Если пользователь не аутентифицирован, возвращаем undefined
    if (!isAuthenticated || !user?.user_id) {
      return undefined;
    }
    
    // Fallback: если userConfig не готов, но user есть, создаем configurable вручную
    return {
      configurable: {
        user_id: user.user_id,
      },
    };
  }, [userConfig?.configurable, loading, isAuthenticated, user?.user_id]);

  const thread = useStream<GraphState>({
    apiUrl: `${window.location.protocol}//${window.location.host}/graph`,
    assistantId: "chat",
    messagesKey: "messages",
    reconnectOnMount: true,
    threadId: threadId === undefined ? null : threadId,
    // @ts-ignore - configurable поддерживается API, но не включен в типы
    // ВАЖНО: Всегда передаем configurable, если он доступен
    configurable: threadConfig?.configurable,
    onThreadId: async (threadId: string) => {
      setCurrentThreadId(threadId);
      onThreadIdChange?.(threadId);
      navigate(`/threads/${threadId}`);
      // Сохраняем чат при создании нового threadId (await для гарантии сохранения)
      // Используем сохраненное первое сообщение, если оно есть
      const firstMessage = pendingFirstMessageRef.current;
      await saveChat(threadId, firstMessage || undefined);
      // Очищаем ref после использования
      pendingFirstMessageRef.current = null;
      // Принудительно обновляем список чатов после создания нового чата
      await refreshChats();
      
      // ВАЖНО: Перезагружаем настройки пользователя из БД при создании нового чата
      // Это гарантирует, что токены и другие настройки будут актуальными
      if (loadSettings) {
        try {
          console.log("[CHAT] Перезагрузка настроек пользователя при создании нового чата...");
          await loadSettings(true); // forceReload = true
          console.log("[CHAT] Настройки пользователя перезагружены из БД");
        } catch (error) {
          console.error("[CHAT] Ошибка при перезагрузке настроек пользователя:", error);
          // Не прерываем процесс создания потока, если перезагрузка настроек не удалась
        }
      }
      
          // ВАЖНО: Обновляем Redis при создании потока
      if (isAuthenticated && user?.user_id && token) {
        try {
          const redisResult = await addThreadToRedisSession(threadId, token);
          
          // Если отладка включена, показываем сообщение только в консоли (без UI блока)
          if (settings.debugMode) {
            console.log(`✅ Redis обновлен: ${redisResult.message}`);
            console.log(`   user_id: ${redisResult.user_id}, thread_id: ${redisResult.thread_id}`);
            // Убрано добавление отладочного сообщения в UI при создании потока/сессии
          }
        } catch (error) {
          console.error("⚠️ Не удалось обновить Redis при создании потока:", error);
          // Не прерываем процесс создания потока, если Redis недоступен
        }
      }
    },
    onCustomEvent: (event, options) => {
      options.mutate((prev) => {
        // @ts-ignore
        const ui = uiMessageReducer(prev.ui ?? [], event);
        return { ...prev, ui };
      });
    },
  });

  // Логируем изменения user_id для отладки
  useEffect(() => {
    if (threadConfig?.configurable?.user_id) {
      console.log(`✅ Chat: user_id готов для использования: ${threadConfig.configurable.user_id}`);
    } else if (!loading && isAuthenticated && user?.user_id) {
      console.warn("⚠️ Chat: user_id недоступен в threadConfig, но user есть. Проверьте useUserConfig.");
    } else if (!loading && !isAuthenticated) {
      console.warn("⚠️ Chat: Пользователь не аутентифицирован, поток не будет создан");
    }
  }, [threadConfig?.configurable?.user_id, loading, isAuthenticated, user?.user_id]);

  useEffect(() => {
    onThreadReady?.(thread as unknown as UseStream<GraphState>);
  }, [thread, onThreadReady]);

  useEffect(() => {
    if (threadId) {
      setCurrentThreadId(threadId);
      onThreadIdChange?.(threadId);
      // Сохраняем чат, если он загружается по threadId (может быть еще не в истории)
      // Используем async функцию для await
      (async () => {
        await saveChat(threadId);
      })();
      
      // ВАЖНО: Перезагружаем настройки пользователя из БД при переходе на существующий чат
      // Это гарантирует, что токены и другие настройки будут актуальными
      // (на случай, если они были изменены в другом окне или вкладке)
      (async () => {
        if (loadSettings) {
          try {
            console.log("[CHAT] Перезагрузка настроек пользователя при переходе на чат...");
            await loadSettings(true); // forceReload = true
            console.log("[CHAT] Настройки пользователя перезагружены из БД");
          } catch (error) {
            console.error("[CHAT] Ошибка при перезагрузке настроек пользователя:", error);
          }
        }
      })();
      
      // Очищаем отладочные сообщения при смене потока
      if (settings.debugMode) {
        setDebugMessages([]);
      }
    }
  }, [threadId, onThreadIdChange, saveChat, settings.debugMode, loadSettings]);

  const stableMessages: Message[] = useStableMessages(thread) as Message[];
  const lastMessagesCountRef = useRef<number>(0);

  // Сохраняем/обновляем чат при получении новых сообщений (от пользователя или системы)
  useEffect(() => {
    const updateChat = async () => {
      if (currentThreadId && stableMessages.length > 0) {
      // Проверяем, появились ли новые сообщения
      const hasNewMessages = stableMessages.length > lastMessagesCountRef.current;
      
      if (hasNewMessages) {
        // Ищем последнее сообщение от пользователя для обновления заголовка
        const humanMessages = stableMessages.filter(
          (msg: Message) => msg.type === "human",
        );
        
        if (humanMessages.length > 0) {
          const lastHumanMessage = humanMessages[humanMessages.length - 1];
          const messageContent =
            typeof lastHumanMessage.content === "string"
              ? lastHumanMessage.content
              : Array.isArray(lastHumanMessage.content)
                ? lastHumanMessage.content
                    .map((item: any) =>
                      typeof item === "string" ? item : item.text || "",
                    )
                    .join(" ")
                : "";
          
          // Сохраняем чат после каждого сообщения пользователя или ответа системы
          // Это обновит дату обновления чата
          await saveChat(currentThreadId, messageContent);
          // Обновляем список чатов после сохранения
          await refreshChats();
        } else {
          // Если нет сообщений от пользователя, но есть новые сообщения (ответ системы),
          // все равно обновляем чат для обновления даты
          await saveChat(currentThreadId);
          // Обновляем список чатов после сохранения
          await refreshChats();
        }
        
        // Обновляем счетчик сообщений
        lastMessagesCountRef.current = stableMessages.length;
      }
    } else if (currentThreadId && stableMessages.length === 0) {
      // Если сообщений нет, сбрасываем счетчик
      lastMessagesCountRef.current = 0;
    }
    };
    
    updateChat();
  }, [currentThreadId, stableMessages, saveChat, refreshChats]);

  return (
    <SelectedAttachmentsProvider>
      <div className="w-full flex p-5 max-[900px]:p-0 max-[900px]:mt-[75px]">
        <div className="flex max-w-[900px] mx-auto h-full flex-col flex-1 bg-card text-card-foreground backdrop-blur-2xl rounded-lg overflow-hidden shadow-lg dark:shadow-2xl max-[900px]:shadow-none print:overflow-visible print:shadow-none">
          {/* Шапка чата с информацией о модели */}
          <div className="flex items-center justify-between px-5 py-3 border-b border-border print:hidden">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold text-foreground">Чат</h2>
            </div>
            <div className="flex items-center gap-3">
              <ChatModelInfo />
              {/* Круглая кнопка печати */}
              <button
                onClick={() => window.print()}
                className="w-8 h-8 rounded-full bg-muted hover:bg-muted/80 flex items-center justify-center transition-colors"
                title="Печать чата"
              >
                <Printer size={16} className="text-muted-foreground" />
              </button>
            </div>
          </div>
          <MessageList messages={stableMessages ?? []} thread={thread}>
            {/* Показываем отладочные сообщения только при включенной отладке */}
            {settings.debugMode && debugMessages.map((debugMsg) => (
              <DebugMessage
                key={debugMsg.id}
                message={debugMsg.message}
                type={debugMsg.type}
              />
            ))}
          </MessageList>
          <InputArea 
            thread={thread} 
            onFirstMessage={(message) => {
              // Сохраняем первое сообщение для использования при создании threadId
              pendingFirstMessageRef.current = message;
            }}
          />
        </div>
      </div>
    </SelectedAttachmentsProvider>
  );
};

export default Chat;
