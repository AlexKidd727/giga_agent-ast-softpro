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
  
  // Если режим отладки включен, не показываем анимацию (там уже есть ToolExecuting)
  if (settings.debugMode) {
    return null;
  }
  
  // Показываем анимацию только когда:
  // 1. Есть сообщения
  // 2. Последнее сообщение НЕ от AI (значит работа еще не завершена, ожидается ответ системы)
  // 3. Поток загружается (isLoading = true) - идет обращение к бэкенду
  // 4. Режим отладки выключен
  // 5. НЕ в момент завершения работы (когда последнее сообщение от AI - работа завершена, ожидается ответ пользователя)
  
  const lastMessage = messages.length > 0 ? messages[messages.length - 1] : null;
  const isWaitingForUser = lastMessage?.type === "ai"; // Если последнее сообщение от AI - работа завершена, ожидается ответ пользователя
  const isProcessing = thread?.isLoading && !isWaitingForUser; // Обработка идет, но не завершена
  
  // Проверяем, есть ли активные tool_calls (выполняются инструменты)
  // @ts-ignore
  const hasActiveToolCalls = lastMessage?.tool_calls && lastMessage.tool_calls.length > 0;
  
  // Проверяем, есть ли последнее сообщение от tool (результат выполнения инструмента)
  // @ts-ignore
  const lastToolMessage = messages.length > 0 && messages[messages.length - 1]?.type === "tool";
  
  // Показываем анимацию в двух случаях:
  // 1. Когда выполняется инструмент (есть tool_calls)
  // 2. Когда получен результат от инструмента, но основной агент еще обрабатывает (isLoading = true)
  const shouldShow = isProcessing && (hasActiveToolCalls || lastToolMessage || messages.length > 0);
  
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
