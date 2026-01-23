import React, { useState } from "react";
import { Message } from "@langchain/langgraph-sdk";
import {
  AttachmentBubble,
  AttachmentsContainer,
  EnlargedImage,
  ImagePreview,
} from "./Attachments.tsx";
import { FileData } from "../interfaces.ts";
import OverlayPortal from "./OverlayPortal.tsx";

interface MessageProps {
  message: Message;
}

const MessageAttachments: React.FC<MessageProps> = ({ message }) => {
  // @ts-ignore
  const uploads = (message.additional_kwargs?.files ?? []) as FileData[];
  const [enlargedImage, setEnlargedImage] = useState<string | null>(null);

  const toFilesUrl = (p: string) => {
    if (!p) return "/files/";
    // p может быть: "name.ext", "files/name.ext", "/files/name.ext"
    let rel = p;
    if (rel.startsWith("/files/")) rel = rel.slice("/files/".length);
    if (rel.startsWith("files/")) rel = rel.slice("files/".length);
    return `/files/${rel}`;
  };

  const openLink = (url: string) => {
    // @ts-ignore
    window.open(url, "_blank").focus();
  };

  return (
    <>
      {uploads.length > 0 && (
        <AttachmentsContainer
          style={{ justifyContent: "flex-end", marginTop: "0" }}
        >
          {uploads.map((u: FileData, idx) => {
            // Получаем имя файла из пути (с проверкой типа)
            const pathStr = typeof u.path === 'string' ? u.path : '';
            const fileName = pathStr.split('/').pop() || pathStr.replace("files/", "") || 'Файл';
            const isImage = u.file_type === "image";
            
            return (
              <AttachmentBubble
                key={idx}
                onClick={() =>
                  isImage
                    ? setEnlargedImage(toFilesUrl(u.path))
                    : openLink(toFilesUrl(u.path))
                }
              >
                {isImage && (
                  <ImagePreview src={toFilesUrl(u.path)} />
                )}
                
                {/* Всегда показываем название файла */}
                <span style={{ 
                  maxWidth: isImage ? '120px' : '200px', 
                  overflow: 'hidden', 
                  textOverflow: 'ellipsis', 
                  whiteSpace: 'nowrap',
                  fontSize: '13px'
                }}>
                  {fileName}
                </span>
              </AttachmentBubble>
            );
          })}
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

export default MessageAttachments;
