import React, { useEffect, useMemo, useRef, useState } from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { dracula } from "react-syntax-highlighter/dist/cjs/styles/prism";
import { Message } from "@langchain/langgraph-sdk";
import Spinner from "./Spinner.tsx";
import { ChevronRight } from "lucide-react";
import OverlayPortal from "./OverlayPortal.tsx";
import { PROGRESS_AGENTS, TOOL_MAP, BROWSER_USE_NAME } from "../config.ts";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { GraphState } from "../interfaces.ts";
import MessageAttachment from "./attachments/MessageAttachment.tsx";
import { triggerModelUpdate } from "./ChatModelInfo.tsx";

interface ToolMessageProps {
  message: Message;
  name: string;
}

interface ToolExecProps {
  messages: Message[];
  thread?: UseStream<GraphState>;
}

interface AgentNode {
  text: string;
  image?: string;
}

export const ToolExecuting = ({ messages, thread }: ToolExecProps) => {
  // @ts-ignore
  // Безопасное получение имени инструмента с проверкой на undefined
  const name = messages && messages.length > 0 && messages[messages.length - 1]?.tool_calls?.length
    ? // @ts-ignore
      (messages[messages.length - 1]?.tool_calls[0]?.name || "none")
    : "none";
  
  const agentProgress: AgentNode | null = useMemo(() => {
    // @ts-ignore
    const uis = (thread.values.ui ?? []).filter(
      // @ts-ignore
      (el) => el.name === "agent_execution",
    );
    if (uis.length) {
      let image = uis.at(-1).props.image;
      let text;
      if (uis.at(-1).props.node_text) text = uis.at(-1).props.node_text;
      // @ts-ignore
      const agent = PROGRESS_AGENTS[name];
      if (agent) {
        text = agent[uis.at(-1).props.node];
      }
      if (text || image) {
        return {
          text,
          image,
        };
      }
      return null;
    }
    return null;
  }, [thread?.values.ui]);
  
  // Проверяем, что name существует и является строкой перед использованием в TOOL_MAP
  const toolName = (name && typeof name === "string" && name in TOOL_MAP) 
    ? `: ${TOOL_MAP[name as keyof typeof TOOL_MAP]} ` 
    : "";
  const displayedRef = useRef<string>(""); // накапливаемый текст
  const [displayed, setDisplayed] = useState<string>("");
  const idxRef = useRef<number>(0);

  useEffect(() => {
    displayedRef.current = "";
    setDisplayed("");
    // Проверяем, что text существует и является строкой
    if (!agentProgress?.text || typeof agentProgress.text !== "string") return;
    idxRef.current = 0;
    const words = agentProgress.text;
    let timer: NodeJS.Timeout;

    const step = () => {
      // Проверяем, что words все еще строка
      if (typeof words !== "string" || !words.length) return;
      // случайный размер чанка: от 1 до 4 слов
      const chunkSize = Math.max(3, Math.floor(Math.random() * 6) + 1);
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
      }
    };

    step();

    return () => clearTimeout(timer);
    // @ts-ignore
  }, [agentProgress]);
  // Проверяем условия для отображения индикатора:
  // 1. Не должно быть прерывания
  // 2. Должны быть сообщения
  // 3. В последнем сообщении должны быть tool_calls (инструмент вызван)
  // 4. Поток должен загружаться (isLoading = true) - инструмент выполняется
  // 5. Последнее сообщение не должно быть tool message (результат еще не получен)
  const lastMessage = messages && messages.length > 0 ? messages[messages.length - 1] : null;
  // @ts-ignore
  const hasToolCalls = lastMessage?.tool_calls && lastMessage.tool_calls.length > 0;
  const isToolMessage = lastMessage?.type === "tool";
  const isLoading = thread?.isLoading ?? false;
  
  if (
    thread?.interrupt ||
    !messages ||
    !hasToolCalls ||
    !isLoading ||
    isToolMessage
  ) {
    return null;
  }
  
  
  return (
    <>
      <div className="flex items-start mb-2 px-9">
        <div className="flex flex-col border border-2 border-border text-foreground p-4 rounded-lg flex-1 cursor-pointer max-w-full justify-center">
          <div className="flex items-center">
            <span className="text-sm ml-4">
              <span className="flex items-center">
                Инструмент выполняется{toolName} <Spinner size="12" />
              </span>
              {displayed && (
                <>
                  <span className="text-transparent bg-gradient-to-r from-muted-foreground/40 via-muted-foreground/70 to-muted-foreground/40 bg-clip-text animate-pulse">
                    {displayed}
                  </span>
                </>
              )}
              {agentProgress?.image && (
                <>
                  <br />
                  <img
                    style={{ marginTop: "10px", borderRadius: "4px" }}
                    src={`data:image/png;base64,${agentProgress.image}`}
                    width={400}
                  />
                </>
              )}
            </span>
          </div>
        </div>
      </div>
      
    </>
  );
};

const ATTACHMENT_TEXTS = {
  plotly_graph: "В результате работы был сгенерирован график ",
  image: "В результате работы было сгенерировано изображение ",
  html: "В результате работы была сгенерирована HTML-страница",
  audio: "В результате работы было сгенерировано аудио",
  text: "В результате работы был сгенерирован текстовый файл ",
  other: "В результате работы было сгенерировано вложение ",
};

const ToolMessage: React.FC<ToolMessageProps> = ({ message, name }) => {
  const [expanded, setExpanded] = useState(false);
  const [file, setFile] = useState<any | null>(null);

  // Обновляем информацию о модели при получении результата от switch_openrouter_model или reset_to_startup_openrouter_model
  useEffect(() => {
    if (message.type === "tool" && name) {
      const toolName = name.toLowerCase();
      if (toolName.includes("switch_openrouter_model") || 
          toolName.includes("reset_to_startup_openrouter_model")) {
        // Проверяем, что результат успешный (содержит "Успешно" или не содержит "Ошибка")
        const content = typeof message.content === "string" ? message.content : "";
        if (content.includes("Успешно") || 
            (content.includes("переключено") && !content.includes("Ошибка"))) {
          console.log("[ToolMessage] Обнаружено переключение модели, обновляем ChatModelInfo");
          // Небольшая задержка, чтобы бэкенд успел обновить состояние
          setTimeout(() => {
            triggerModelUpdate();
          }, 500);
        }
      }
    }
  }, [message, name]);

  if (message.type !== "tool") {
    return null;
  }

  const attachments: any = message.additional_kwargs?.tool_attachments || [];
  let content: string;
  try {
    // Проверяем, что content существует и является строкой
    const messageContent = message.content;
    if (!messageContent) {
      content = "";
    } else if (typeof messageContent === "string") {
      try {
        // Пробуем распарсить как JSON
        const parsed = JSON.parse(messageContent);
        content = JSON.stringify(parsed, null, 2);
      } catch (e) {
        // Если не JSON, используем как есть
        content = messageContent;
      }
    } else {
      // Если content не строка, преобразуем в строку
      content = String(messageContent);
    }
  } catch (e) {
    console.error("[ToolMessage] Ошибка при обработке content:", e);
    content = String(message.content || "");
  }

  const handleLinkClick = (ev: React.MouseEvent, file: any) => {
    ev.preventDefault();
    setFile(file);
  };

  // Проверяем, что name существует и является строкой перед использованием в TOOL_MAP
  const toolName = (name && typeof name === "string" && name in TOOL_MAP) 
    ? `: ${TOOL_MAP[name as keyof typeof TOOL_MAP]} ` 
    : "";

  return (
    <>
      <div className="flex items-start mb-2 px-9">
        <div className="flex flex-col border border-2 cursor-pointer border-border text-foreground p-4 rounded-lg flex-1 cursor-pointer max-w-full">
          <div
            className="flex items-center"
            onClick={() => setExpanded((prev) => !prev)}
          >
            <span
              className="inline-block mr-2 transition-transform duration-200"
              style={{ transform: expanded ? "rotate(90deg)" : "rotate(0deg)" }}
            >
              <ChevronRight size={16} />
            </span>
            <span className="text-sm flex align-middle">
              Результат выполнения инструмента{toolName}
            </span>
          </div>

          <div
            className={[
              "overflow-auto cursor-text transition-[max-height] duration-700 print:hidden",
              expanded ? "max-h-[400px]" : "max-h-0",
            ].join(" ")}
          >
            <SyntaxHighlighter
              language="json"
              lineProps={{
                style: { wordBreak: "break-word", whiteSpace: "pre-wrap" },
              }}
              style={dracula}
              showLineNumbers
              wrapLines={true}
            >
              {content}
            </SyntaxHighlighter>
          </div>
        </div>
      </div>
      {attachments.length > 0 && (
        <div className="flex flex-col gap-3">
          {attachments.map((att: any) => {
            const fileId = att["file_id"] || att["path"];
            const fileType = att["type"] || att["file_type"] || "image/png";
            // Определяем тип файла из MIME типа
            let displayType = "other";
            if (fileType.startsWith("image/")) {
              displayType = "image";
            } else if (fileType.startsWith("audio/")) {
              displayType = "audio";
            } else if (fileType === "text/html") {
              displayType = "html";
            } else if (fileType.startsWith("text/")) {
              displayType = "text";
            }
            return (
              <a
                key={fileId}
                href=""
                onClick={(ev) => handleLinkClick(ev, { ...att, path: fileId })}
                className="px-9 ml-3 text-foreground text-xs underline"
              >
                {
                  // @ts-ignore
                  ATTACHMENT_TEXTS[displayType] || ATTACHMENT_TEXTS["other"]
                }{" "}
                {fileId}
              </a>
            );
          })}
        </div>
      )}
      <OverlayPortal isVisible={!!file} onClose={() => setFile(null)}>
        <div className="bg-card rounded-lg p-2.5">
          {file ? (
            <MessageAttachment path={file["file_id"] || file["path"]} alt={""} fullScreen={true} />
          ) : (
            <></>
          )}
        </div>
      </OverlayPortal>
    </>
  );
};

export default ToolMessage;
