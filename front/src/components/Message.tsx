import React, { useEffect, useMemo, useRef, useState } from "react";
import { Checkpoint, Message as Message_ } from "@langchain/langgraph-sdk";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";
import MessageAttachments from "./MessageAttachments.tsx";
import { TOOL_MAP } from "../config.ts";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { GraphState, GraphTemplate } from "../interfaces.ts";
import MessageEditor from "./MessageEditor.tsx";
import { ChevronLeft, ChevronRight, Pencil, RefreshCw, Copy, Check } from "lucide-react";
import { useSelectedAttachments } from "../hooks/SelectedAttachmentsContext.tsx";
import TextMarkdown from "./attachments/TextMarkdown.tsx";
import { useAuth } from "./Auth/AuthContext";
import { useUserConfig, useUserId } from "../hooks/useUserConfig";
import { useSettings } from "./Settings.tsx";
import { Badge } from "./ui/badge";

/**
 * Безопасное преобразование content в строку.
 * Обрабатывает случаи когда content может быть массивом, объектом или другим типом.
 */
function safeContentToString(content: unknown): string {
  if (content === null || content === undefined) {
    return "";
  }
  if (typeof content === "string") {
    return content;
  }
  if (Array.isArray(content)) {
    // Если массив, объединяем текстовые элементы
    return content
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object") {
          // Обработка объектов типа {type: "text", text: "..."}
          if (item.type === "text" && typeof item.text === "string") {
            return item.text;
          }
          // Пропускаем изображения и другие типы
          if (item.type === "image_url" || item.type === "image") {
            return "";
          }
          return JSON.stringify(item);
        }
        return String(item);
      })
      .filter(Boolean)
      .join("\n");
  }
  if (typeof content === "object") {
    // Если объект с полем text
    if ("text" in content && typeof (content as any).text === "string") {
      return (content as any).text;
    }
    return JSON.stringify(content);
  }
  return String(content);
}

function BranchSwitcher({
  thread,
  message,
}: {
  thread?: UseStream<GraphState, GraphTemplate>;
  message: Message_;
}) {
  if (!thread) return null;
  const meta = thread.getMessagesMetadata(message);
  const branch = meta?.branch;
  const branchOptions = meta?.branchOptions;
  if (!branchOptions || !branch) return null;
  const onSelect = (branch: any) => thread.setBranch(branch);
  const index = branchOptions.indexOf(branch);

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={() => {
          const prevBranch = branchOptions[index - 1];
          if (!prevBranch) return;
          onSelect(prevBranch);
        }}
        disabled={thread.isLoading}
        className="transition-transform duration-200 bg-transparent border-0 text-foreground p-0 disabled:opacity-50 cursor-pointer hover:scale-110 disabled:hover:scale-100"
      >
        <ChevronLeft size={16} />
      </button>
      <span className="text-[13px]">
        {index + 1} / {branchOptions.length}
      </span>
      <button
        onClick={() => {
          const nextBranch = branchOptions[index + 1];
          if (!nextBranch) return;
          onSelect(nextBranch);
        }}
        disabled={thread.isLoading}
        className="transition-transform duration-200 bg-transparent border-0 text-foreground p-0 disabled:opacity-50 cursor-pointer hover:scale-110 disabled:hover:scale-100"
      >
        <ChevronRight size={16} />
      </button>
    </div>
  );
}

interface MessageProps {
  message: Message_;
  onWrite: () => void;
  onWriteEnd?: () => void;
  writeMessage?: boolean;
  thread?: UseStream<GraphState, GraphTemplate>;
}

const Message: React.FC<MessageProps> = ({
  message,
  onWrite,
  onWriteEnd,
  thread,
  writeMessage = false,
}) => {
  // 2) хук для постепенной «печати» чанков
  const displayedRef = useRef<string>(""); // накапливаемый текст
  const [displayed, setDisplayed] = useState<string>("");
  const [edit, setEdit] = useState<boolean>(false);
  const [showEdit, setShowEdit] = useState<boolean>(false);
  const [copied, setCopied] = useState<boolean>(false);
  const [modelInfo, setModelInfo] = useState<{ provider?: string; displayName?: string } | null>(null);
  const { setSelectedAttachments, clear } = useSelectedAttachments();
  const { user, isAuthenticated } = useAuth();
  const userConfig = useUserConfig();
  const userId = useUserId();
  const { settings } = useSettings();

  const idxRef = useRef<number>(0);

  useEffect(() => {
    if (message.type === "human" && !writeMessage) {
      // @ts-ignore
      displayedRef.current = message.additional_kwargs.user_input;
      // @ts-ignore
      setDisplayed(message.additional_kwargs.user_input);
      return;
    }
    if (message.type !== "ai" && !writeMessage) {
      // если не ai — сразу пишем весь текст
      const contentStr = safeContentToString(message.content);
      displayedRef.current = contentStr;
      setDisplayed(contentStr);
      return;
    }

    // @ts-ignore
    if (message.additional_kwargs["rendered"]) {
      // Проверяем наличие reasoning_content в additional_kwargs
      // @ts-ignore
      const reasoningContent = message.additional_kwargs?.reasoning_content;
      let fullContent = safeContentToString(message.content);
      
      // Проверяем, есть ли tool_calls в сообщении
      // Если есть, то весь content должен быть в блоке <thinking>
      // @ts-ignore
      const hasToolCalls = message.tool_calls && message.tool_calls.length > 0;
      
      // Если есть tool_calls и content не содержит <thinking>, оборачиваем весь content в <thinking>
      if (hasToolCalls && fullContent && !fullContent.includes("<thinking>")) {
        fullContent = `<thinking>\n${fullContent.trim()}\n</thinking>`;
      }
      
      // Проверяем, весь ли текст находится внутри <thinking></thinking>
      // Если да, и есть разделитель "---", то применяем его для разделения рассуждений и основного ответа
      const thinkingMatch = fullContent.match(/<thinking>([\s\S]*?)<\/thinking>/);
      const isEntirelyInThinking = thinkingMatch && thinkingMatch[0].trim() === fullContent.trim();
      
      // Применяем разделитель "---" только если весь текст в <thinking>
      if (isEntirelyInThinking && fullContent.includes("---")) {
        // Извлекаем содержимое из <thinking>
        const thinkingContent = thinkingMatch[1].trim();
        // Разделяем по "---"
        const parts = thinkingContent.split("---", 2);
        const reasoningPart = parts[0].trim();
        const mainContent = parts[1]?.trim() || "";
        
        if (reasoningPart && mainContent) {
          // Форматируем рассуждения в теги <thinking> и добавляем основной ответ
          const thinkingBlock = `<thinking>\n${reasoningPart}\n</thinking>\n\n`;
          fullContent = thinkingBlock + mainContent;
        } else if (reasoningPart) {
          // Если есть только рассуждения, оставляем как есть
          fullContent = fullContent;
        } else {
          // Если до "---" ничего нет, убираем <thinking> и оставляем только основной контент
          fullContent = mainContent;
        }
      } else {
        // КРИТИЧЕСКИ ВАЖНО: Если content пустой или содержит только reasoning_content,
        // значит весь ответ попал в reasoning_content (например, после обобщения)
        // В этом случае reasoning_content становится основным контентом
        const contentIsEmpty = !fullContent || fullContent.trim() === "";
        const contentIsOnlyReasoning = fullContent.trim() === (reasoningContent?.trim() || "");
        
        if (reasoningContent && reasoningContent.trim()) {
          if (contentIsEmpty || contentIsOnlyReasoning) {
            // Весь ответ в reasoning_content - делаем его основным контентом
            // и не добавляем блок <thinking>
            fullContent = reasoningContent.trim();
          } else if (!fullContent.includes("<thinking>")) {
            // Обычный случай: есть и reasoning_content, и основной контент
            // Форматируем reasoning_content в теги <thinking> и добавляем в начало content
            const thinkingBlock = `<thinking>\n${reasoningContent.trim()}\n</thinking>\n\n`;
            fullContent = thinkingBlock + fullContent;
          }
        }
      }
      
      displayedRef.current = fullContent;
      setDisplayed(fullContent);
      return;
    }

    // Проверяем, есть ли tool_calls в сообщении
    // Если есть, то весь content должен быть в блоке <thinking>
    // @ts-ignore
    const hasToolCalls = message.tool_calls && message.tool_calls.length > 0;
    let contentToDisplay = safeContentToString(message.content);
    
    // Удаляем теги <tool_call> и </tool_call> из контента перед обработкой
    contentToDisplay = contentToDisplay.replace(/<tool_call>[\s\S]*?<\/tool_call>/gi, '');
    contentToDisplay = contentToDisplay.replace(/<\/?tool_call>/gi, '');
    
    // Если есть tool_calls и content не содержит <thinking>, оборачиваем весь content в <thinking>
    if (hasToolCalls && contentToDisplay && !contentToDisplay.includes("<thinking>")) {
      contentToDisplay = `<thinking>\n${contentToDisplay.trim()}\n</thinking>`;
    }
    
    const words = contentToDisplay;
    let timer: NodeJS.Timeout;

    const step = () => {
      // случайный размер чанка: от 1 до 4 слов
      const chunkSize = Math.max(10, Math.floor(Math.random() * 20) + 1);
      const next = Math.min(idxRef.current + chunkSize, words.length);
      // добавляем words[idx..next]
      displayedRef.current =
        displayedRef.current + words.slice(idxRef.current, next);
      setDisplayed(displayedRef.current);
      idxRef.current = next;
      if (idxRef.current < words.length) {
        // случайная задержка: 20–120 мс
        const delay = 20 + Math.random() * 40;
        timer = setTimeout(step, delay);
      } else {
        onWriteEnd?.();
      }
    };

    step();

    return () => clearTimeout(timer);
    // @ts-ignore
  }, [message.content, message.additional_kwargs, message.type, message.tool_calls]);
  const normalizedContent = useMemo(() => {
    let md = displayed;

    // Удаляем теги <tool_call> и </tool_call> из контента
    md = md.replace(/<tool_call>[\s\S]*?<\/tool_call>/gi, '');
    md = md.replace(/<\/?tool_call>/gi, '');

    // 1) перед каждым ``` вставляем гарантированно пустую строку
    md = md.replace(/(^|\n)(```[^\n]*)/g, "$1\n$2");
    md = md.replace(
      /<thinking>([\s\S]*?)<\/thinking>/g,
      (_, content) =>
        `<thinking>${content.replace(/\n/g, "<br>")}</thinking>\n`,
    );
    // md = md.replace(/\$\\?([^\$]+)\$/g, "\n$$$$$1$$$$\n");
    return md;
  }, [displayed]);

  useEffect(() => {
    onWrite();
  }, [normalizedContent, onWrite]);

  // Загружаем информацию о модели для AI сообщений
  useEffect(() => {
    if (message.type === "ai") {
      const fetchModelInfo = async () => {
        try {
          const url = userId ? `/api/model-info?user_id=${encodeURIComponent(userId)}` : "/api/model-info";
          const response = await fetch(url);
          if (response.ok) {
            const data = await response.json();
            setModelInfo({
              provider: data.provider,
              displayName: data.displayName || data.model_name || data.model,
            });
          }
        } catch (error) {
          console.error("[Message] Ошибка при получении информации о модели:", error);
        }
      };
      fetchModelInfo();
    }
  }, [message.type, userId]);

  const onCopy = async () => {
    try {
      // Удаляем блоки размышлений (<thinking>...</thinking>) из markdown перед копированием
      let contentToCopy = normalizedContent;
      // Удаляем теги <tool_call> и </tool_call>
      contentToCopy = contentToCopy.replace(/<tool_call>[\s\S]*?<\/tool_call>/gi, '');
      contentToCopy = contentToCopy.replace(/<\/?tool_call>/gi, '');
      // Удаляем блоки <thinking> с содержимым (включая HTML-теги внутри)
      contentToCopy = contentToCopy.replace(/<thinking>[\s\S]*?<\/thinking>/gi, '');
      // Удаляем оставшиеся пустые строки (более 2 подряд)
      contentToCopy = contentToCopy.replace(/\n{3,}/g, '\n\n');
      // Удаляем пробелы в начале и конце
      contentToCopy = contentToCopy.trim();
      
      // Копируем очищенный markdown контент в буфер обмена
      await navigator.clipboard.writeText(contentToCopy);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Ошибка при копировании:', err);
      // Fallback для старых браузеров
      // Удаляем блоки размышлений перед копированием
      let contentToCopy = normalizedContent;
      // Удаляем теги <tool_call> и </tool_call>
      contentToCopy = contentToCopy.replace(/<tool_call>[\s\S]*?<\/tool_call>/gi, '');
      contentToCopy = contentToCopy.replace(/<\/?tool_call>/gi, '');
      contentToCopy = contentToCopy.replace(/<thinking>[\s\S]*?<\/thinking>/gi, '');
      contentToCopy = contentToCopy.replace(/\n{3,}/g, '\n\n');
      contentToCopy = contentToCopy.trim();
      
      const textArea = document.createElement('textarea');
      textArea.value = contentToCopy;
      textArea.style.position = 'fixed';
      textArea.style.opacity = '0';
      document.body.appendChild(textArea);
      textArea.select();
      try {
        document.execCommand('copy');
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      } catch (fallbackErr) {
        console.error('Ошибка при копировании (fallback):', fallbackErr);
      }
      document.body.removeChild(textArea);
    }
  };

  const onRefresh = () => {
    const parentMessage = thread?.messages.filter(
      (_: Message_, i: number) =>
        i + 1 < thread.messages.length &&
        thread.messages[i + 1].id === message.id,
    ); // Получаем сообщение которое идет до AI сообщения
    // TODO: Сейчас это нужно, чтобы giga_agent адекватно работал с aegra, так как в их API нельзя просто передавать checkpoint (без input)
    const meta = thread?.getMessagesMetadata(message);
    const parentCheckpoint = meta?.branch
      ? ({
          ...meta?.firstSeenState?.parent_checkpoint,
          thread_id: meta.firstSeenState?.checkpoint.thread_id,
          checkpoint_id:
            meta.branch.split(">").length > 1
              ? meta.branch.split(">")[0]
              : meta.branch,
        } as Checkpoint)
      : meta?.firstSeenState?.parent_checkpoint;

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

    thread?.submit(
      { messages: parentMessage },
      { 
        checkpoint: parentCheckpoint,
        // @ts-ignore - configurable поддерживается API, но не включен в типы
        configurable: configurable,
      },
    );
  };

  return (
    <div
      style={{ marginBottom: "20px", padding: "0 20px" }}
      onMouseEnter={() => setShowEdit(true)}
      onMouseLeave={() => setShowEdit(false)}
    >
      {edit ? (
        <MessageEditor
          message={message}
          onCancel={() => {
            setEdit(false);
            clear();
          }}
          thread={thread}
        />
      ) : (
        <>
          <div
            className={[
              "flex py-2.5",
              message.type === "human" ? "justify-end" : "justify-start",
            ].join(" ")}
          >
            <div
              className={[
                message.type === "human"
                  ? "max-w-[80%] w-auto p-4 pt-4 pb-4 rounded-[25px] bg-secondary text-foreground dark:text-[#2c2c2c] overflow-x-auto"
                  : "max-w-full w-full p-0 bg-transparent",
                "markdown",
              ].join(" ")}
            >
              <TextMarkdown>{normalizedContent}</TextMarkdown>

              {
                // Скрываем tool_calls когда отладка выключена
                // @ts-ignore
                message.tool_calls &&
                  settings.debugMode &&
                  // @ts-ignore
                  message.tool_calls.map((tool_call, index) => (
                    <div key={index} className="mt-2">
                      <div>
                        Действие:{" "}
                        {tool_call.name in TOOL_MAP
                          ? // @ts-ignore
                            `${TOOL_MAP[tool_call.name]} `
                          : tool_call.name}
                      </div>
                      <SyntaxHighlighter
                        language={
                          tool_call.name === "python" ? "python" : "json"
                        }
                        style={vscDarkPlus}
                        customStyle={{
                          // Для темной темы: умеренно темно-синий (#2d3f5a)
                          // Для светлой темы: бледно-серо-голубой (#e8f0f5)
                          backgroundColor: typeof window !== "undefined" && document.documentElement.classList.contains("dark")
                            ? "#2d3f5a"
                            : "#e8f0f5",
                        }}
                      >
                        {tool_call.name === "python"
                          ? tool_call.args.code
                          : JSON.stringify(tool_call.args)}
                      </SyntaxHighlighter>
                    </div>
                  ))
              }
              {
                //@ts-ignore
                message.additional_kwargs &&
                //@ts-ignore
                message.additional_kwargs.selected &&
                //@ts-ignore
                Object.keys(message.additional_kwargs.selected).length > 0 ? (
                  <div className="mt-1 text-muted-foreground text-xs pointer-events-none">
                    Выбраны вложения:{" "}
                    {
                      //@ts-ignore
                      Object.keys(message.additional_kwargs.selected).length
                    }
                  </div>
                ) : (
                  <></>
                )
              }
            </div>
          </div>
          {
            //@ts-ignore
            message.additional_kwargs &&
            //@ts-ignore
            message.additional_kwargs.files?.length ? (
              <div style={{ marginBottom: "8px" }}>
                <MessageAttachments message={message} />
              </div>
            ) : (
              <></>
            )
          }
          {/* Кнопки для AI сообщений - копировать всегда видна, перезапустить при наведении */}
          {message.type === "ai" && (
            <div className="flex flex-grow-0 gap-2 justify-start items-center mt-2">
              {/* Кнопка копирования - всегда видима */}
              <button
                disabled={!thread || thread.isLoading}
                onClick={onCopy}
                className="transition-transform duration-200 cursor-pointer bg-transparent border-0 text-foreground p-0 disabled:opacity-50 hover:scale-110 disabled:hover:scale-100"
                title="Скопировать ответ в формате markdown"
              >
                {copied ? <Check size={16} /> : <Copy size={16} />}
              </button>
              {/* Кнопка перезапуска - показывается при наведении */}
              <button
                disabled={!thread || thread.isLoading}
                onClick={onRefresh}
                className={[
                  "transition-all duration-200 cursor-pointer bg-transparent border-0 text-foreground p-0 disabled:opacity-50 hover:scale-110 disabled:hover:scale-100",
                  showEdit ? "opacity-100" : "opacity-0",
                ].join(" ")}
                title="Повторить запрос"
              >
                <RefreshCw size={16} />
              </button>
              {/* Подпись с информацией о провайдере и модели */}
              {modelInfo && (
                <div className="flex items-center gap-1.5 ml-2 text-xs text-muted-foreground">
                  {modelInfo.provider && (
                    <>
                      <Badge 
                        variant={
                          modelInfo.provider.toLowerCase() === "openrouter" ? "default" :
                          modelInfo.provider.toLowerCase() === "deepseek" ? "secondary" :
                          modelInfo.provider.toLowerCase() === "openai" ? "outline" : "outline"
                        } 
                        className="text-[10px] px-1.5 py-0 h-4"
                      >
                        {modelInfo.provider.toLowerCase() === "openrouter" ? "OpenRouter" :
                         modelInfo.provider.toLowerCase() === "deepseek" ? "DeepSeek" :
                         modelInfo.provider.toLowerCase() === "openai" ? "OpenAI" :
                         modelInfo.provider}
                      </Badge>
                      <span className="opacity-50">/</span>
                    </>
                  )}
                  <span className="font-medium">{modelInfo.displayName || "Модель"}</span>
                </div>
              )}
            </div>
          )}
          
          {/* Остальные кнопки - показываются при наведении */}
          <div
            className={[
              "flex flex-grow-0 gap-2 transition-opacity duration-200",
              showEdit ? "opacity-100" : "opacity-0",
              message.type === "ai" ? "justify-start" : "justify-end",
            ].join(" ")}
          >
            {message.type === "human" && (
              <button
                disabled={!thread || thread.isLoading}
                onClick={() => {
                  setEdit(true);
                  if (
                    //@ts-ignore
                    message.additional_kwargs &&
                    //@ts-ignore
                    message.additional_kwargs.selected &&
                    //@ts-ignore
                    Object.keys(message.additional_kwargs.selected).length > 0
                  )
                    // @ts-ignore
                    setSelectedAttachments(message.additional_kwargs.selected);
                  else clear();
                }}
                className="transition-transform duration-200 bg-transparent border-0 text-foreground p-0 disabled:opacity-50 cursor-pointer hover:scale-110 disabled:hover:scale-100"
              >
                <Pencil size={16} />
              </button>
            )}
            <BranchSwitcher thread={thread} message={message} />
          </div>
        </>
      )}
    </div>
  );
};

export default React.memo(
  Message,
  (prev, next) => prev.message === next.message && prev.thread === next.thread,
);
