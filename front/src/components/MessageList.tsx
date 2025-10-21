import React, {
  useEffect,
  useRef,
  forwardRef,
  useImperativeHandle,
} from "react";
import styled from "styled-components";
import Message from "./Message.tsx";
import ToolMessage, { ToolExecuting } from "./ToolMessage.tsx";
import { Message as Message_ } from "@langchain/langgraph-sdk";
import ThinkingIndicator from "./ThinkingIndicator.tsx";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { GraphState } from "../interfaces.ts";
import ChatError from "./ChatError.tsx";

const MessageListContainer = styled.div`
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  @media (max-width: 900px) {
    padding: 0;
  }
  @media print {
    overflow: visible;
  }
`;

interface MessageListProps {
  messages: Message_[];
  thread?: UseStream<GraphState>;
  children?: React.ReactNode;
}

const MessageList = forwardRef<any, MessageListProps>(
  ({ messages, thread, children }, ref) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const atBottomRef = useRef<boolean>(true);

    // Отслеживаем позицию скролла: находимся ли мы внизу (10%)
    const handleScroll = () => {
      const el = containerRef.current;
      if (!el) return;
      const { scrollTop, clientHeight, scrollHeight } = el;
      atBottomRef.current = scrollTop + clientHeight >= scrollHeight - 100;
    };

    const scroll = () => {
      const el = containerRef.current;
      if (!el) return;
      if (atBottomRef.current) {
        el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
      }
    };
    useImperativeHandle(ref, () => ({
      scrollToBottom: () => {
        scroll();
      },
    }));
    // Автоскролл вниз при добавлении нового сообщения, только если были внизу
    useEffect(() => {
      scroll();
    }, [messages]);

    return (
      <MessageListContainer ref={containerRef} onScroll={handleScroll}>
        {children}
        {messages.map((message, idx) =>
          message.type === "tool" ? (
            <ToolMessage
              key={idx}
              message={message}
              name={
                // @ts-ignore
                messages[idx - 1]?.tool_calls &&
                // @ts-ignore
                messages[idx - 1]?.tool_calls[0]
                  ? // @ts-ignore
                    messages[idx - 1]?.tool_calls[0].name
                  : ""
              }
            />
          ) : (
            <Message
              key={idx}
              message={message}
              onWrite={scroll}
              thread={thread}
            />
          ),
        )}
        <ChatError thread={thread} />
        <ToolExecuting messages={messages} thread={thread} />
        <ThinkingIndicator messages={messages} thread={thread} />
      </MessageListContainer>
    );
  },
);

export default MessageList;
