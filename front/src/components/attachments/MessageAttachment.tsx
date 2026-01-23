import React, { useEffect, useState } from "react";
import styled from "styled-components";
import { StoreClient } from "@langchain/langgraph-sdk/client";
import Graph from "./Graph.tsx";
import Text from "./Text.tsx";
import HTMLPage from "./HTMLPage.tsx";
import Image from "./Image.tsx";
import Audio from "./Audio.tsx";

interface MessageAttachmentProps {
  path: string;
  fullScreen?: boolean;
  alt?: string;
}

const Placeholder = styled.div`
  width: 100%;
  padding-top: 56.25%; /* подложка под изображение, чтобы не прыгал layout */
  background-color: #2d2d2d;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100px;
  
  &::after {
    content: "Загрузка...";
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    color: #999;
    font-size: 14px;
  }
`;

const client = new StoreClient({
  apiUrl: `${window.location.protocol}//${window.location.host}/graph`,
});

const MessageAttachment: React.FC<MessageAttachmentProps> = ({
  path,
  alt,
  fullScreen,
}) => {
  const [attachment, setAttachment] = useState<any | null>(null);
  const [error, setError] = useState<boolean>(false);

  const detectFileType = (
    filePath: string,
  ): "image" | "audio" | "html" | "text" | "plotly_graph" | "other" => {
    const lower = filePath.toLowerCase();
    const dotIdx = lower.lastIndexOf(".");
    const ext = dotIdx >= 0 ? lower.slice(dotIdx + 1) : "";
    const imageExt = ["png", "jpg", "jpeg", "gif", "webp", "bmp", "svg"];
    const audioExt = ["mp3", "wav", "ogg", "m4a", "aac", "flac"];
    const htmlExt = ["html", "htm"];
    // JSON файлы в папке offloads - это графики Plotly
    // Проверяем путь на наличие offloads или tinkoff_agent (типичные пути для графиков)
    if (ext === "json" && (lower.includes("offloads") || lower.includes("_agent"))) {
      return "plotly_graph";
    }
    const textExt = [
      "txt",
      "md",
      "csv",
      "json",
      "xml",
      "yaml",
      "yml",
      "toml",
      "ini",
      "cfg",
      "conf",
    ];
    if (imageExt.includes(ext)) return "image";
    if (audioExt.includes(ext)) return "audio";
    if (htmlExt.includes(ext)) return "html";
    if (textExt.includes(ext)) return "text";
    return "other";
  };

  useEffect(() => {
    setError(false);
    setAttachment(null);
    
    // Если path начинается с /files/, это файл на диске - используем его напрямую
    if (path.startsWith("/files/")) {
      const file_type = detectFileType(path);
      // Для файлов на диске сразу устанавливаем attachment с путем
      // Image/Audio компоненты сами загрузят файл по этому пути
      setAttachment({ 
        file_type, 
        path: path,
        data: null // Файл будет загружен напрямую по URL
      });
      return;
    }
    
    // Если path начинается с /home/jupyter, это тоже файл на диске
    if (path.startsWith("/home/jupyter")) {
      const file_type = detectFileType(path);
      // Преобразуем путь /home/jupyter в /files/
      const normalizedPath = path.replace("/home/jupyter", "/files");
      setAttachment({ 
        file_type, 
        path: normalizedPath,
        data: null
      });
      return;
    }
    
    // Иначе path это file_id (UUID) - ищем в store
    // Пытаемся получить файл из разных namespace в зависимости от типа
    // Сначала пробуем audio, потом html, потом attachments
    const tryGetItem = async () => {
      // Пробуем audio
      try {
        const res = await client.getItem(["audio"], path);
        if (res?.value) {
          setAttachment(res.value);
          return;
        }
      } catch (e) {
        // Продолжаем
      }
      // Пробуем html
      try {
        const res = await client.getItem(["html"], path);
        if (res?.value) {
          setAttachment(res.value);
          return;
        }
      } catch (e) {
        // Продолжаем
      }
      // Пробуем attachments (по умолчанию)
      try {
        const res = await client.getItem(["attachments"], path);
        if (res?.value) {
          setAttachment(res.value);
          return;
        }
      } catch (e) {
        // Если не найдено в store, возможно это путь к файлу - пробуем использовать напрямую
        if (path.startsWith("/")) {
          const file_type = detectFileType(path);
          // Нормализуем путь: если начинается с /home/jupyter, преобразуем в /files/
          const normalizedPath = path.startsWith("/home/jupyter") 
            ? path.replace("/home/jupyter", "/files")
            : path.startsWith("/files/") 
              ? path 
              : `/files/${path}`;
          setAttachment({ 
            file_type, 
            path: normalizedPath,
            data: null
          });
        } else {
          setError(true);
        }
      }
    };
    tryGetItem();
  }, [path]);

  if (error) {
    return <div>Ошибка загрузки вложения {alt || ""}</div>;
  }
  if (!attachment) {
    return <Placeholder />; // можно заменить на спиннер или skeleton
  }
  if (attachment["file_type"] === "plotly_graph") {
    return <Graph data={attachment} alt={alt} id={path} />;
  } else if (attachment["file_type"] === "text") {
    return <Text data={attachment} alt={alt} id={path} />;
  } else if (attachment["file_type"] === "html") {
    return (
      <HTMLPage
        data={attachment}
        alt={alt}
        id={path}
        fullScreen={fullScreen ? fullScreen : false}
      />
    );
  } else if (attachment["file_type"] === "image") {
    return <Image data={attachment} alt={alt} id={path} />;
  } else if (attachment["file_type"] === "audio") {
    return <Audio data={attachment} alt={alt} id={path} />;
  } else if (attachment["file_type"] === "other") {
    // Для файлов типа application/zip и прочих "other" показываем ссылку на скачивание.
    // Важно: attachment.path может быть:
    // - "/files/<name>"
    // - "files/<name>"
    // - "<name>"
    const rawPath: string = attachment?.path || "";
    let href = rawPath;
    if (href.startsWith("files/")) href = `/files/${href.slice("files/".length)}`;
    else if (href && !href.startsWith("/files/") && !href.startsWith("/")) href = `/files/${href}`;
    // Если путь пустой — показываем ошибку
    if (!href) {
      return <div>Ошибка загрузки вложения {alt || ""}</div>;
    }
    return (
      <div className="text-sm">
        <a href={href} target="_blank" rel="noreferrer" className="underline">
          Скачать файл
        </a>
        <div className="opacity-70 text-xs mt-1">{href}</div>
      </div>
    );
  } else {
    return <div>Ошибка загрузки вложения {alt || ""}</div>;
  }
};

export default React.memo(
  MessageAttachment,
  (prev, next) => prev.path === next.path && prev.alt === next.alt,
);
