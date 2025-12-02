// ThinkingIndicator.tsx
import { RefreshCw, AlertTriangle } from "lucide-react";
import React, { useRef, useEffect, useState } from "react";
import styled from "styled-components";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { GraphState } from "@/interfaces.ts";
import { useAuth } from "./Auth/AuthContext";
import { useUserConfig, useUserId } from "../hooks/useUserConfig";
import { useSettings } from "./Settings.tsx";

// Стили для переливающегося текста
const Wrapper = styled.div`
  padding: 10px 34px;
`;

const Inner = styled.div`
  background: #ee3e36;
  padding: 15px 10px;
  border-radius: 8px;
  border: 3px solid firebrick;
  display: flex;
  align-items: center;
  color: white;
`;

const RefreshButton = styled.div`
  padding: 5px;
  border-radius: 8px;
  margin-left: 4px;
  padding-bottom: 3px;
  cursor: pointer;
  transition: background-color 0.2s;
  &:hover {
    background: #d33831;
  }
`;

interface ChatErrorProps {
  thread?: UseStream<GraphState>;
}

const ChatError = ({ thread }: ChatErrorProps) => {
  const { user, isAuthenticated } = useAuth();
  const userConfig = useUserConfig();
  const userId = useUserId();
  const { settings } = useSettings();
  
  // Отслеживание повторяющихся ошибок
  const errorHistoryRef = useRef<Array<{ error: string; timestamp: number }>>([]);
  const [repeatedError, setRepeatedError] = useState<string | null>(null);
  const [shouldStop, setShouldStop] = useState(false);
  
  // Получаем текст ошибки
  const errorMessage = (thread?.error && typeof thread.error === 'object' && 'message' in thread.error
    ? String((thread.error as { message: unknown }).message)
    : thread?.error ? String(thread.error) : "");
  
  useEffect(() => {
    if (!errorMessage || thread?.isLoading) {
      return;
    }
    
    // Добавляем ошибку в историю
    const now = Date.now();
    errorHistoryRef.current.push({
      error: errorMessage,
      timestamp: now,
    });
    
    // Оставляем только последние 5 ошибок
    errorHistoryRef.current = errorHistoryRef.current.slice(-5);
    
    // Проверяем, есть ли 3 одинаковых ошибки подряд
    if (errorHistoryRef.current.length >= 3) {
      const lastThree = errorHistoryRef.current.slice(-3);
      const allSame = lastThree.every(
        (err) => err.error === errorMessage
      );
      
      if (allSame && !settings.debugMode) {
        // Если отладка выключена и 3 одинаковых ошибки - останавливаем
        setRepeatedError(errorMessage);
        setShouldStop(true);
        console.error("❌ Обнаружено 3 одинаковых ошибки подряд. Остановка выполнения.");
      } else {
        setRepeatedError(null);
        setShouldStop(false);
      }
    }
  }, [errorMessage, thread?.isLoading, settings.debugMode]);
  
  // Сбрасываем историю при успешном выполнении
  useEffect(() => {
    if (!thread?.error && !thread?.isLoading) {
      errorHistoryRef.current = [];
      setRepeatedError(null);
      setShouldStop(false);
    }
  }, [thread?.error, thread?.isLoading]);
  
  if (!thread?.error || thread.isLoading) {
    return null;
  }
  
  // Если отладка выключена и обнаружена повторяющаяся ошибка - показываем финальное сообщение
  if (shouldStop && repeatedError && !settings.debugMode) {
    return (
      <Wrapper>
        <Inner style={{ background: "#d32f2f", borderColor: "#b71c1c" }}>
          <AlertTriangle size={20} style={{ marginRight: "8px" }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: "bold", marginBottom: "4px" }}>
              Критическая ошибка: повторяющаяся ошибка обнаружена 3 раза подряд
            </div>
            <div style={{ fontSize: "14px", opacity: 0.9 }}>
              {repeatedError}
            </div>
            <div style={{ fontSize: "12px", opacity: 0.7, marginTop: "8px" }}>
              Выполнение остановлено. Включите режим отладки для детальной информации.
            </div>
          </div>
        </Inner>
      </Wrapper>
    );
  }
  
  // Если отладка выключена, показываем только финальную ошибку без возможности повтора
  if (!settings.debugMode) {
    return (
      <Wrapper>
        <Inner>
          <AlertTriangle size={20} style={{ marginRight: "8px" }} />
          <div style={{ flex: 1 }}>
            Произошла ошибка: {errorMessage}
          </div>
        </Inner>
      </Wrapper>
    );
  }

  // В режиме отладки показываем кнопку повтора
  const handleRetry = () => {
    // Проверяем, что пользователь аутентифицирован перед повторной отправкой
    if (!isAuthenticated || !userId) {
      console.error("❌ Невозможно повторить отправку: пользователь не аутентифицирован");
      return;
    }
    
    // ВАЖНО: Всегда передаем configurable с user_id
    const configurable = userConfig?.configurable || {
      user_id: userId,
    };
    
    // Валидация: проверяем, что user_id не пустой и не 'anonymous'
    if (!configurable.user_id || configurable.user_id.trim().toLowerCase() === 'anonymous') {
      console.error(`❌ Невозможно повторить отправку: невалидный user_id: '${configurable.user_id}'`);
      return;
    }
    
    // @ts-ignore
    thread?.submit(undefined, {
      // @ts-ignore - configurable поддерживается API, но не включен в типы
      configurable: configurable,
    });
  };

  return (
    <Wrapper>
      <Inner>
        В чате произошла ошибка{" "}
        <RefreshButton onClick={handleRetry}>
          <RefreshCw color={"white"} size={16} />
        </RefreshButton>
      </Inner>
    </Wrapper>
  );
};

export default ChatError;
