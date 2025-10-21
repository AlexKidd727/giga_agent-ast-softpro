import React, { useEffect, useMemo, useRef, useState } from "react";
import styled from "styled-components";
import { Checkpoint, Message as Message_ } from "@langchain/langgraph-sdk";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";
import MessageAttachments from "./MessageAttachments.tsx";
import { TOOL_MAP } from "../config.ts";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { GraphState, GraphTemplate } from "../interfaces.ts";
import MessageEditor from "./MessageEditor.tsx";
import { ChevronLeft, ChevronRight, Pencil, RefreshCw } from "lucide-react";
import { useSelectedAttachments } from "../hooks/SelectedAttachmentsContext.tsx";
import TextMarkdown from "./attachments/TextMarkdown.tsx";

const MessageContainer = styled.div<{
  type: "function" | "ai" | "human" | "tool" | "system" | "remove";
}>`
  display: flex;
  justify-content: ${({ type }) =>
    type === "human" ? "flex-end" : "flex-start"};
  padding: 10px 0;
`;

const MessageBubble = styled.div<{
  type: "function" | "ai" | "human" | "tool" | "system" | "remove";
}>`
  max-width: ${({ type }) => (type === "human" ? "80%" : "100%")};
  width: ${({ type }) => (type === "human" ? "auto" : "100%")};
  padding: ${({ type }) =>
    type === "human" ? "1rem 1.5rem 0.5rem 1.5rem;" : "0"};
  border-radius: 25px;
  background-color: ${({ type }) =>
    type === "human" ? "#2d2d2d" : "transparent"};
  color: #ffffff;
  overflow-x: ${({ type }) => (type === "human" ? "auto" : "visible")};
`;

const ActionSection = styled.div`
  margin-top: 8px;
`;

const Buttons = styled.div`
  display: flex;
  flex-grow: 0;
  justify-content: end;
`;

const MessageButtons = styled(Buttons)<{ showEdit: boolean; type: string }>`
  gap: 8px;
  transition: opacity 0.2s ease;
  opacity: ${({ showEdit }) => (showEdit ? 1 : 0)};
  justify-content: ${({ type }) => (type === "ai" ? "start" : "end")};
`;

const MessageButton = styled.button<{ disabled: boolean }>`
  transition: transform 0.2s ease;
  cursor: ${({ disabled }) => (disabled ? "default" : "pointer")};
  background: transparent;
  border: none;
  color: white;
  padding: 0;

  &:disabled {
    opacity: 0.5;
  }

  &:hover {
    transform: scale(${({ disabled }) => (disabled ? 1.0 : 1.1)});
  }
`;

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
    <Buttons>
      <MessageButton
        onClick={() => {
          const prevBranch = branchOptions[index - 1];
          if (!prevBranch) return;
          onSelect(prevBranch);
        }}
        disabled={thread.isLoading}
      >
        <ChevronLeft size={16} />
      </MessageButton>
      <span style={{ fontSize: "13px" }}>
        {index + 1} / {branchOptions.length}
      </span>
      <MessageButton
        onClick={() => {
          const nextBranch = branchOptions[index + 1];
          if (!nextBranch) return;
          onSelect(nextBranch);
        }}
        disabled={thread.isLoading}
      >
        <ChevronRight size={16} />
      </MessageButton>
    </Buttons>
  );
}

const SelectedCounter = styled.div`
  margin-top: 6px;
  color: #9e9e9e;
  font-size: 12px;
  pointer-events: none;
`;

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
  const { setSelectedAttachments, clear } = useSelectedAttachments();

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
      displayedRef.current = message.content as string;
      setDisplayed(message.content as string);
      return;
    }

    // @ts-ignore
    if (message.additional_kwargs["rendered"]) {
      displayedRef.current = message.content as string;
      setDisplayed(message.content as string);
      return;
    }

    const words = message.content;
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
  }, [message.content, message.additional_kwargs, message.type]);
  const normalizedContent = useMemo(() => {
    let md = displayed;

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

    thread?.submit(
      { messages: parentMessage },
      { checkpoint: parentCheckpoint },
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
          <MessageContainer type={message.type}>
            <MessageBubble type={message.type} className={"markdown"}>
              <TextMarkdown>{normalizedContent}</TextMarkdown>

              {
                // @ts-ignore
                message.tool_calls &&
                  // @ts-ignore
                  message.tool_calls.map((tool_call, index) => (
                    <ActionSection key={index}>
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
                      >
                        {tool_call.name === "python"
                          ? tool_call.args.code
                          : JSON.stringify(tool_call.args)}
                      </SyntaxHighlighter>
                    </ActionSection>
                  ))
              }
              {
                //@ts-ignore
                message.additional_kwargs &&
                //@ts-ignore
                message.additional_kwargs.selected &&
                //@ts-ignore
                Object.keys(message.additional_kwargs.selected).length > 0 ? (
                  <SelectedCounter>
                    Выбраны вложения:{" "}
                    {
                      //@ts-ignore
                      Object.keys(message.additional_kwargs.selected).length
                    }
                  </SelectedCounter>
                ) : (
                  <></>
                )
              }
            </MessageBubble>
          </MessageContainer>
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
          <MessageButtons showEdit={showEdit} type={message.type}>
            {message.type === "human" && (
              <MessageButton
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
              >
                <Pencil size={16} />
              </MessageButton>
            )}
            {message.type === "ai" && (
              <MessageButton
                disabled={!thread || thread.isLoading}
                onClick={onRefresh}
              >
                <RefreshCw size={16} />
              </MessageButton>
            )}
            <BranchSwitcher thread={thread} message={message} />
          </MessageButtons>
        </>
      )}
    </div>
  );
};

export default React.memo(
  Message,
  (prev, next) => prev.message === next.message && prev.thread === next.thread,
);
