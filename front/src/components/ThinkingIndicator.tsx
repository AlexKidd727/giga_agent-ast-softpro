// ThinkingIndicator.tsx
import React from "react";
import { Message as Message_ } from "@langchain/langgraph-sdk";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { GraphState } from "../interfaces.ts";
import { useSettings } from "./Settings.tsx";
import Spinner from "./Spinner.tsx";

interface ThinkingProps {
  messages: Message_[];
  thread?: UseStream<GraphState>;
}

const ThinkingIndicator = ({ messages, thread }: ThinkingProps) => {
  const { settings } = useSettings();
  
  const lastMessage = messages.length > 0 ? messages[messages.length - 1] : null;
  const isProcessing = thread?.isLoading ?? false;
  
  // Проверяем, есть ли активные tool_calls (выполняются инструменты)
  // @ts-ignore
  const hasActiveToolCalls = lastMessage?.tool_calls && lastMessage.tool_calls.length > 0;
  
  // Проверяем, есть ли последнее сообщение от tool (результат выполнения инструмента)
  // @ts-ignore
  const lastToolMessage = messages.length > 0 && messages[messages.length - 1]?.type === "tool";
  
  // РЕЖИМ ОТЛАДКИ: показываем "Думаю..." сразу после отправки сообщения пользователем
  if (settings.debugMode) {
    // Показываем индикатор "Думаю..." когда:
    // 1. Последнее сообщение от пользователя (type === "human")
    // 2. Поток загружается (isLoading = true)
    // 3. Еще нет tool_calls (инструмент еще не вызван - тогда показывается ToolExecuting)
    // 4. Еще нет ответа от AI
    const isLastMessageHuman = lastMessage?.type === "human";
    const isWaitingForUser = lastMessage?.type === "ai"; // Если последнее сообщение от AI - работа завершена
    
    // Скрываем индикатор если:
    // - Нет сообщений
    // - Последнее сообщение от AI (работа завершена)
    // - Поток не загружается
    // - Уже есть tool_calls (тогда показывается ToolExecuting)
    // - Уже есть tool message (результат инструмента получен)
    if (
      messages.length <= 0 ||
      isWaitingForUser ||
      !isProcessing ||
      hasActiveToolCalls ||
      lastToolMessage ||
      !isLastMessageHuman
    ) {
      return null;
    }
    
    // Показываем простой индикатор "Думаю..." в режиме отладки
    return (
      <div className="px-[34px] py-[20px] flex items-center gap-3">
        <Spinner size="20px" />
        <div className="flex flex-col gap-1">
          <span className="text-foreground font-medium">
            Думаю...
          </span>
          <span className="text-xs text-muted-foreground">
            Обработка запроса
          </span>
        </div>
      </div>
    );
  }
  
  // РЕЖИМ БЕЗ ОТЛАДКИ: показываем детальную информацию о процессе
  // Показываем анимацию только когда:
  // 1. Есть сообщения
  // 2. Последнее сообщение НЕ от AI (значит работа еще не завершена, ожидается ответ системы)
  // 3. Поток загружается (isLoading = true) - идет обращение к бэкенду
  // 4. НЕ в момент завершения работы (когда последнее сообщение от AI - работа завершена, ожидается ответ пользователя)
  
  const isWaitingForUser = lastMessage?.type === "ai"; // Если последнее сообщение от AI - работа завершена, ожидается ответ пользователя
  
  // Показываем анимацию в двух случаях:
  // 1. Когда выполняется инструмент (есть tool_calls)
  // 2. Когда получен результат от инструмента, но основной агент еще обрабатывает (isLoading = true)
  const shouldShow = isProcessing && !isWaitingForUser && (hasActiveToolCalls || lastToolMessage || messages.length > 0);
  
  if (
    messages.length <= 0 ||
    isWaitingForUser ||
    !shouldShow
  ) {
    return null;
  }
  
  // Определяем текст в зависимости от состояния
  let statusText = "Обработка запроса...";
  if (hasActiveToolCalls) {
    // @ts-ignore
    const toolName = lastMessage?.tool_calls?.[0]?.name || "";
    // Проверяем, является ли это агентом
    const isAgent = toolName && (toolName.includes("_agent") || toolName === "email_agent" || toolName === "tinkoff_agent" || toolName === "researcher_agent");
    if (isAgent) {
      statusText = "Выполнение задачи суб-агента...";
    } else {
      statusText = "Выполнение инструмента...";
    }
  } else if (lastToolMessage) {
    statusText = "Обработка результата основным агентом...";
  }
  
  // Анимация ожидания с индикатором загрузки
  return (
    <div className="px-[34px] py-[20px] flex items-center gap-3">
      <Spinner size="20px" />
      <div className="flex flex-col gap-1">
        <span className="text-foreground font-medium">
          {statusText}
        </span>
        <span className="text-xs text-muted-foreground">
          Пожалуйста, подождите
        </span>
      </div>
    </div>
  );
};

export default ThinkingIndicator;
