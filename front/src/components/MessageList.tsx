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
  /* Избегаем нежелательных прыжков прокрутки из-за scroll anchoring */
  overflow-anchor: none;
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
    const autoScrollEnabledRef = useRef<boolean>(true);
    const bottomSentinelRef = useRef<HTMLDivElement>(null);
    const userScrollIntentRef = useRef<boolean>(false);
    const resetIntentTimeoutRef = useRef<number | null>(null);
    const rafIdRef = useRef<number | null>(null);
    const isSafariRef = useRef<boolean>(
      typeof navigator !== "undefined" &&
        /safari/i.test(navigator.userAgent) &&
        !/chrome|android/i.test(navigator.userAgent),
    );

    // Наблюдаем за «сентинелом» внизу списка, чтобы понять, включать ли авто-скролл
    useEffect(() => {
      const root = containerRef.current;
      const sentinel = bottomSentinelRef.current;
      if (!root || !sentinel) return;

      const observer = new IntersectionObserver(
        ([entry]) => {
          if (entry.isIntersecting) {
            // Включаем авто-скролл только при достижении низа
            autoScrollEnabledRef.current = true;
          }
          // Не выключаем авто-скролл на больших рывках контента
        },
        { root, threshold: 0.99 },
      );

      observer.observe(sentinel);
      return () => observer.disconnect();
    }, []);

    const maybeAutoScroll = () => {
      const el = containerRef.current;
      if (!el) return;
      if (!autoScrollEnabledRef.current) return;
      if (rafIdRef.current !== null) return; // коалесцируем множественные вызовы за кадр
      rafIdRef.current = window.requestAnimationFrame(() => {
        rafIdRef.current = null;
        const current = containerRef.current;
        if (!current) return;
        if (isSafariRef.current) {
          // Safari: избегаем smooth, чтобы не было скачков вверх
          current.scrollTop = current.scrollHeight;
        } else {
          current.scrollTo({ top: current.scrollHeight, behavior: "smooth" });
        }
      });
    };

    const markUserScrollIntent = () => {
      userScrollIntentRef.current = true;
      if (resetIntentTimeoutRef.current) {
        window.clearTimeout(resetIntentTimeoutRef.current);
      }
      resetIntentTimeoutRef.current = window.setTimeout(() => {
        userScrollIntentRef.current = false;
      }, 300);
    };

    const handleUserScroll = () => {
      const el = containerRef.current;
      if (!el) return;
      if (!userScrollIntentRef.current) return;
      const nearBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 100;
      if (!nearBottom) {
        // Отключаем авто-скролл только если пользователь явно ушёл от низа
        autoScrollEnabledRef.current = false;
      }
    };
    useImperativeHandle(ref, () => ({
      scrollToBottom: () => {
        const current = containerRef.current;
        if (!current) return;
        if (isSafariRef.current) {
          // Safari: избегаем smooth, чтобы не было скачков вверх
          current.scrollTop = current.scrollHeight;
        } else {
          current.scrollTo({ top: current.scrollHeight, behavior: "smooth" });
        }
      },
    }));
    // Автоскролл вниз при добавлении нового сообщения, только если авто-скролл включён
    useEffect(() => {
      maybeAutoScroll();
    }, [messages]);

    // При первом монтировании прокручиваем к низу
    useEffect(() => {
      const el = containerRef.current;
      if (!el) return;
      // Первичная прокрутка без анимации
      el.scrollTop = el.scrollHeight;
      return () => {
        if (rafIdRef.current !== null) {
          window.cancelAnimationFrame(rafIdRef.current);
          rafIdRef.current = null;
        }
      };
    }, []);

    return (
      <MessageListContainer
        ref={containerRef}
        onWheel={markUserScrollIntent}
        onTouchStart={markUserScrollIntent}
        onScroll={handleUserScroll}
      >
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
              onWrite={maybeAutoScroll}
              thread={thread}
            />
          ),
        )}
        <ChatError thread={thread} />
        <ToolExecuting messages={messages} thread={thread} />
        <ThinkingIndicator messages={messages} thread={thread} />
        <div ref={bottomSentinelRef} style={{ height: 1 }} />
      </MessageListContainer>
    );
  },
);

export default MessageList;
