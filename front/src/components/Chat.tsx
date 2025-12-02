import React, { useCallback, useEffect, useState, useMemo } from "react";
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

interface ChatProps {
  onThreadIdChange?: (threadId: string) => void;
  onThreadReady?: (thread: UseStream<GraphState>) => void;
}

const Chat: React.FC<ChatProps> = ({ onThreadIdChange, onThreadReady }) => {
  const navigate = useNavigate();
  const { threadId } = useParams<{ threadId?: string }>();
  const { saveChat } = useChatHistory();
  const [currentThreadId, setCurrentThreadId] = useState<string | null>(null);
  const [debugMessages, setDebugMessages] = useState<Array<{ id: string; message: string; type: "info" | "success" | "warning" | "error" }>>([]);
  const { user, loading, isAuthenticated, token } = useAuth();
  const userConfig = useUserConfig();
  const { settings } = useSettings();

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
      // Сохраняем чат при создании нового threadId
      saveChat(threadId);
      
      // ВАЖНО: Обновляем Redis при создании потока
      if (isAuthenticated && user?.user_id && token) {
        try {
          const redisResult = await addThreadToRedisSession(threadId, token);
          
          // Если отладка включена, показываем сообщение в консоли и в чате
          if (settings.debugMode) {
            console.log(`✅ Redis обновлен: ${redisResult.message}`);
            console.log(`   user_id: ${redisResult.user_id}, thread_id: ${redisResult.thread_id}`);
            
            // Добавляем отладочное сообщение в чат
            setDebugMessages((prev) => [
              ...prev,
              {
                id: `redis-${threadId}-${Date.now()}`,
                message: `Redis обновлен: ${redisResult.message}\nuser_id: ${redisResult.user_id}\nthread_id: ${redisResult.thread_id}`,
                type: "success" as const,
              },
            ]);
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
      saveChat(threadId);
      
      // Очищаем отладочные сообщения при смене потока
      if (settings.debugMode) {
        setDebugMessages([]);
      }
    }
  }, [threadId, onThreadIdChange, saveChat, settings.debugMode]);

  const stableMessages: Message[] = useStableMessages(thread) as Message[];

  // Сохраняем/обновляем чат при получении сообщений от пользователя
  useEffect(() => {
    if (currentThreadId && stableMessages.length > 0) {
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
        // Обновляем чат с последним сообщением (это обновит дату обновления)
        saveChat(currentThreadId, messageContent);
      }
    }
  }, [currentThreadId, stableMessages, saveChat]);

  return (
    <SelectedAttachmentsProvider>
      <div className="w-full flex p-5 max-[900px]:p-0 max-[900px]:mt-[75px]">
        <div className="flex max-w-[900px] mx-auto h-full flex-col flex-1 bg-card text-card-foreground backdrop-blur-2xl rounded-lg overflow-hidden shadow-lg dark:shadow-2xl max-[900px]:shadow-none print:overflow-visible print:shadow-none">
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
          <InputArea thread={thread} />
        </div>
      </div>
    </SelectedAttachmentsProvider>
  );
};

export default Chat;
