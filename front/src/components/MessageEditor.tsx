import React, { useCallback, useEffect, useRef, useState } from "react";
import styled from "styled-components";
import { FileData, GraphState } from "../interfaces.ts";
import { useFileUpload } from "../hooks/useFileUploads.ts";
import { Paperclip } from "lucide-react";
import {
  AttachmentBubble,
  AttachmentsContainer,
  CircularProgress,
  EnlargedImage,
  ImagePreview,
  ProgressOverlay,
  RemoveButton,
} from "./Attachments.tsx";
import { Checkpoint, HumanMessage, Message } from "@langchain/langgraph-sdk";
import OverlayPortal from "./OverlayPortal.tsx";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { useSelectedAttachments } from "../hooks/SelectedAttachmentsContext.tsx";

const InputContainer = styled.div`
  padding: 16px;
  background-color: #2d2d2d;
  border-radius: 8px;
  position: relative;
  @media print {
    display: none;
  }
`;

const InputRow = styled.div`
  display: flex;
  align-items: flex-end;
  gap: 8px;
  position: relative;
`;

const TextArea = styled.textarea`
  flex: 1;
  min-height: 60px;
  max-height: 200px;
  resize: none;
  font-family:
    -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu,
    Cantarell, "Open Sans", "Helvetica Neue", sans-serif;
  padding: 12px;
  border: none;
  border-radius: 6px;
  background-color: #2d2d2d;
  color: #ffffff;
  font-size: 16px;
  line-height: 1.4;
  overflow-y: auto;
  outline: none;

  &::placeholder {
    color: #999999;
  }
`;

const FileInput = styled.input`
  display: none;
`;

const IconButton = styled.button`
  padding: 10px;
  border: none;
  border-radius: 8px;
  background-color: #2d2d2d;
  color: #ffffff;
  font-size: 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background-color 0.2s;

  &:hover {
    background-color: #3b3b3b;
  }

  &:disabled {
    background-color: #2d2d2d;
    cursor: not-allowed;
  }
`;

const SendButton = styled(IconButton)`
  background-color: #fff;
  color: black;

  &:hover {
    background-color: #e7e7e7;
  }
`;

const CancelButton = styled(IconButton)`
  background-color: #000;
  color: white;

  &:hover {
    background-color: #101010;
  }
`;

const SelectedCounter = styled.div<{ $visible: boolean }>`
  margin-top: 6px;
  color: #9e9e9e;
  font-size: 12px;
  position: absolute;
  bottom: 8px;
  left: 80px;
  opacity: ${({ $visible }) => ($visible ? 1 : 0)};
  transform: translateY(${({ $visible }) => ($visible ? 0 : 4)}px);
  transition: ${({ $visible }) =>
    $visible ? "opacity 100ms ease, transform 100ms ease" : "none"};
  pointer-events: none;
`;

interface MessageEditorProps {
  message: Message;
  onCancel: () => void;
  thread?: UseStream<GraphState>;
}

const MAX_TEXTAREA_HEIGHT = 200;

const MessageEditor: React.FC<MessageEditorProps> = ({
  message,
  onCancel,
  thread,
}) => {
  const textRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [enlargedImage, setEnlargedImage] = useState<string | null>(null);
  const { uploadFiles, setExistingFiles, items, removeItem, getAllFileData } =
    useFileUpload();
  const [messageText, setMessageText] = useState("");
  const { selected } = useSelectedAttachments();
  const selectedCount = Object.keys(selected).length;

  useEffect(() => {
    // @ts-ignore
    setMessageText(message.additional_kwargs?.user_input);
    // @ts-ignore
    const initialFiles: FileData[] = message.additional_kwargs?.files ?? [];
    setExistingFiles(initialFiles);
  }, [message, setExistingFiles]);

  // при первом рендере и при очистке
  useEffect(() => {
    autoResize();
  }, [messageText]);

  // автоподгон высоты
  const autoResize = () => {
    const el = textRef.current;
    if (!el) return;
    el.style.height = "auto";
    const newHeight = Math.min(el.scrollHeight, MAX_TEXTAREA_HEIGHT);
    el.style.height = `${newHeight}px`;
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      uploadFiles(Array.from(e.target.files));
      e.target.value = "";
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSendMessage();
    }
  };

  const openLink = (url: string) => {
    // @ts-ignore
    window.open(url, "_blank").focus();
  };

  const handleSendMessage = useCallback(async () => {
    const allFiles = getAllFileData();
    const newMessage = {
      type: "human",
      content: messageText,
      // @ts-ignore
      additional_kwargs: {
        user_input: messageText,
        files: allFiles,
        selected: selected,
      },
    } as HumanMessage;

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
      { messages: [newMessage] },
      {
        optimisticValues(prev: GraphState) {
          const prevMessages = prev.messages ?? [];
          const newMessages = [...prevMessages, newMessage];
          newMessages.forEach((el) => {
            if (el.id === message.id) {
              el.content = messageText;
              // @ts-ignore
              el.additional_kwargs.user_input = messageText;
              // @ts-ignore
              el.additional_kwargs.files = allFiles;
            }
          });
          onCancel();
          return { ...prev, messages: newMessages };
        },
        streamMode: ["messages"],
        onDisconnect: "continue",
        checkpoint: parentCheckpoint,
      },
    );
  }, [thread, messageText, message, onCancel, getAllFileData, selected]);

  return (
    <>
      <InputContainer>
        <InputRow>
          <FileInput
            type="file"
            ref={fileInputRef}
            onChange={handleFileChange}
            multiple
          />
          <IconButton
            type="button"
            onClick={() => fileInputRef.current?.click()}
            title="Добавить вложения"
          >
            <Paperclip />
          </IconButton>

          <TextArea
            placeholder="Спросите что-нибудь…"
            ref={textRef}
            value={messageText}
            onChange={(e) => setMessageText(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          <CancelButton type="button" title="Отменить" onClick={onCancel}>
            Отменить
          </CancelButton>
          <SendButton
            type="button"
            title="Отправить"
            onClick={handleSendMessage}
          >
            Отправить
          </SendButton>
        </InputRow>
        <SelectedCounter $visible={selectedCount > 0}>
          Выбрано вложений: {selectedCount}
        </SelectedCounter>
      </InputContainer>
      {items.length > 0 && (
        <AttachmentsContainer>
          {items.map((it, idx) => (
            <AttachmentBubble
              key={idx}
              onClick={() => {
                if (it.kind === "existing") {
                  const f = it.data!;
                  if (f.file_type === "image")
                    setEnlargedImage("/files/" + f.path);
                  else openLink("/files/" + f.path);
                } else if (it.previewUrl) {
                  setEnlargedImage(it.previewUrl);
                }
              }}
            >
              {it.kind === "existing" ? (
                it.data?.file_type === "image" ? (
                  <ImagePreview src={"/files/" + it.data.path} />
                ) : (
                  <span>
                    {it.name ?? it.data?.path.replace(/^files\//, "")}
                  </span>
                )
              ) : it.previewUrl ? (
                <ImagePreview src={it.previewUrl} />
              ) : (
                <span>{it.name}</span>
              )}

              {it.progress < 100 && (
                <ProgressOverlay>
                  <CircularProgress progress={it.progress}>
                    {it.progress}%
                  </CircularProgress>
                </ProgressOverlay>
              )}

              <RemoveButton
                onClick={(e) => {
                  e.stopPropagation();
                  removeItem(idx);
                }}
              >
                ×
              </RemoveButton>
            </AttachmentBubble>
          ))}
        </AttachmentsContainer>
      )}

      {enlargedImage && (
        <OverlayPortal
          isVisible={!!enlargedImage}
          onClose={() => setEnlargedImage(null)}
        >
          <EnlargedImage src={enlargedImage ?? ""} />
        </OverlayPortal>
      )}
    </>
  );
};

export default React.memo(
  MessageEditor,
  (prev, next) =>
    prev.message === next.message &&
    prev.thread === next.thread &&
    prev.onCancel === next.onCancel,
);
