import React, { useEffect, useRef, useState } from "react";
import styled from "styled-components";
import MessageList from "../MessageList";
import InputArea from "../InputArea";
import { useStream } from "@langchain/langgraph-sdk/react";
import { useStableMessages } from "../../hooks/useStableMessages";
import { GraphState } from "../../interfaces";
import { HumanMessage } from "@langchain/langgraph-sdk";
import { useNavigate, useParams } from "react-router-dom";
import { useDemoItems } from "../../hooks/DemoItemsProvider.tsx";
import Message from "../Message.tsx";
import DemoToolBar from "./DemoToolBar.tsx";
import { uiMessageReducer } from "@langchain/langgraph-sdk/react-ui";
import { SelectedAttachmentsProvider } from "../../hooks/SelectedAttachmentsContext.tsx";
import type { UseStream } from "@langchain/langgraph-sdk/react";

const ChatWrapper = styled.div`
  width: 100%;
  display: flex;
  padding: 20px;
  @media (max-width: 900px) {
    padding: 0;
    margin-top: 75px;
  }
`;

const ChatContainer = styled.div`
  display: flex;
  max-width: 900px;
  margin: auto;
  height: 100%;
  flex-direction: column;
  flex: 1;
  background-color: #212121d9;
  backdrop-filter: blur(20px);
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 0 50px #00000075;
  @media print {
    overflow: visible;
    box-shadow: none;
    background-color: #1f1f1f;
  }
  @media (max-width: 900px) {
    background-color: #1f1f1f;
    box-shadow: none;
  }
`;

interface DemoChatProps {
  onContinue: () => void;
  onThreadIdChange?: (threadId: string) => void;
  onThreadReady?: (thread: UseStream<GraphState>) => void;
}

const DemoChat = ({
  onContinue,
  onThreadIdChange,
  onThreadReady,
}: DemoChatProps) => {
  const navigate = useNavigate();
  const { demoIndex } = useParams<{ demoIndex: string }>();
  const { demoItems } = useDemoItems();
  const demoIndexNum = !isNaN(parseInt(demoIndex ?? "0"))
    ? parseInt(demoIndex ?? "0")
    : 0;
  const demoItem = demoItems.at(demoIndexNum);
  const listRef = useRef<any>(null);
  const [firstSent, setFirstSend] = useState(false);
  const [isFinished, setIsFinished] = useState(false);

  const thread = useStream<GraphState>({
    apiUrl: `${window.location.protocol}//${window.location.host}/graph`,
    assistantId: "chat",
    messagesKey: "messages",
    onThreadId: (threadId: string) => {
      onThreadIdChange?.(threadId);
    },
    onFinish: (state) => {
      if (state.next.length === 0) {
        setIsFinished(true);
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
  useEffect(() => {
    onThreadReady?.(thread as unknown as UseStream<GraphState>);
  }, [thread, onThreadReady]);

  const stableMessages = useStableMessages(thread);
  useEffect(() => {
    if (
      // @ts-ignore
      stableMessages.filter((mes) => mes.type === "ai").length >
      (demoItem?.steps ?? 10)
    ) {
      setIsFinished(true);
    }
  }, [stableMessages, demoItem]);

  const handleContinueDemo = () => {
    let nextIndex = (demoIndexNum + 1) % demoItems.length;
    while (!demoItems[nextIndex].active) {
      nextIndex = (nextIndex + 1) % demoItems.length;
    }
    navigate("/demo/" + nextIndex);
    onContinue();
  };

  return (
    <SelectedAttachmentsProvider>
      <ChatWrapper>
        <ChatContainer>
          <MessageList
            messages={stableMessages ?? []}
            thread={thread}
            ref={listRef}
          >
            {!firstSent && (
              <Message
                key={0}
                message={{
                  type: "human",
                  id: "123",
                  content: demoItem?.json_data.message ?? "",
                  // @ts-ignore
                  additional_kwargs: {
                    rendered: false,
                    files: demoItem?.json_data.attachments ?? [],
                  },
                }}
                onWrite={() => {
                  if (listRef.current) listRef.current.scrollToBottom();
                }}
                onWriteEnd={() => {
                  const newMessage = {
                    type: "human",
                    content: demoItem?.json_data.message ?? "",
                    additional_kwargs: {
                      user_input: demoItem?.json_data.message ?? "",
                      files: demoItem?.json_data.attachments ?? [],
                    },
                  } as HumanMessage;

                  thread.submit(
                    { messages: [newMessage] },
                    {
                      optimisticValues(prev) {
                        const prevMessages = prev.messages ?? [];
                        const newMessages = [...prevMessages, newMessage];
                        return { ...prev, messages: newMessages };
                      },
                      streamMode: ["messages"],
                    },
                  );
                  setFirstSend(true);
                }}
                writeMessage={true}
              />
            )}
          </MessageList>
          <InputArea thread={thread} />
        </ChatContainer>
        <DemoToolBar isFinished={isFinished} onContinue={handleContinueDemo} />
      </ChatWrapper>
    </SelectedAttachmentsProvider>
  );
};

export default DemoChat;
