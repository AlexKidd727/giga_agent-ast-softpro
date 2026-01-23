import { useMemo, useState } from "react";
import axios from "axios";
import { FileData } from "../interfaces.ts";
import { useUserId } from "./useUserConfig.tsx";

export interface UploadedFile {
  file: File;
  progress: number;
  previewUrl?: string;
  data?: FileData;
  error?: string;
}

export interface AttachmentItem {
  kind: "existing" | "upload";
  file?: File;
  data?: FileData;
  progress: number;
  previewUrl?: string;
  name?: string;
  error?: string;
}

export function useFileUpload() {
  const [uploads, setUploads] = useState<UploadedFile[]>([]);
  const [existingFiles, setExistingFiles] = useState<FileData[]>([]);
  const userId = useUserId();

  const uploadFiles = async (files: File[]) => {
    const oldIndex = uploads.length;
    
    // Логируем userId для отладки
    console.log(`🔍 useFileUploads: userId = ${userId}`);
    
    for (const [index, file] of files.entries()) {
      const uploadItem: UploadedFile = { file, progress: 0 };
      const addUpload = (item: UploadedFile) =>
        setUploads((prev) => [...prev, item]);

      // Проверяем, является ли файл аудио
      const isAudio = file.type.startsWith("audio/") || 
        /\.(wav|mp3|flac|ogg|webm|m4a)$/i.test(file.name);

      if (file.type.startsWith("image/")) {
        const reader = new FileReader();
        reader.onload = () => {
          addUpload({ ...uploadItem, previewUrl: reader.result as string });
        };
        reader.readAsDataURL(file);
      } else {
        addUpload(uploadItem);
      }

      // Определяем индекс нового элемента (последний)
      const idx = oldIndex + index;
      
      // Если это аудиофайл, сначала отправляем на расшифровку
      if (isAudio) {
        try {
          const sttServiceUrl = import.meta.env.VITE_STT_SERVICE_URL || "/stt";
          const formData = new FormData();
          formData.append("file", file);

          setUploads((prev) => {
            const next = [...prev];
            if (next[idx]) {
              next[idx] = { ...next[idx], progress: 10 };
            }
            return next;
          });

          const transcribeResponse = await fetch(`${sttServiceUrl}/api/transcribe`, {
            method: "POST",
            body: formData,
          });

          if (transcribeResponse.ok) {
            const transcribeResult = await transcribeResponse.json();
            const transcribedText = transcribeResult.text || "";
            
            // Обновляем прогресс
            setUploads((prev) => {
              const next = [...prev];
              if (next[idx]) {
                next[idx] = { ...next[idx], progress: 50 };
              }
              return next;
            });

            // Сохраняем расшифрованный текст в data для последующего использования
            // Продолжаем загрузку файла на сервер
            const uploadFormData = new FormData();
            uploadFormData.append("file", file);

            // Логируем userId перед отправкой
            console.log(`🔍 useFileUploads: Отправка файла "${file.name}", userId = ${userId}`);
            axios
              .post("/files/upload/", uploadFormData, {
                headers: userId ? { "X-User-ID": userId } : {},
                onUploadProgress: (event) => {
                  const pct = event.progress || 0;
                  setUploads((prev) => {
                    const next = [...prev];
                    if (next[idx]) {
                      next[idx] = {
                        ...next[idx],
                        progress: Math.min(50 + Math.round(pct * 50), 100),
                      };
                    }
                    return next;
                  });
                },
              })
              .then((res) => {
                console.log(`📎 useFileUploads: Аудиофайл "${file.name}" загружен и расшифрован:`, res.data);
                setUploads((prev) => {
                  const next = [...prev];
                  if (next[idx]) {
                    const isImage = res.data?.file_type === 'image';
                    const filePath = res.data?.path || res.data?.image_path;
                    const previewUrl = isImage && filePath 
                      ? `/files/${filePath.split('/').pop()}` 
                      : next[idx].previewUrl;
                    next[idx] = {
                      ...next[idx],
                      progress: 100,
                      previewUrl: previewUrl,
                      data: {
                        ...res.data,
                        transcribed_text: transcribedText,
                        is_audio: true,
                      },
                    };
                  }
                  return next;
                });
              })
              .catch(() => {
                setUploads((prev) => prev.filter((u) => u.file !== file));
              });
          } else {
            // Если расшифровка не удалась, просто загружаем файл
            throw new Error("Transcription failed");
          }
        } catch (error) {
          console.warn("Ошибка расшифровки аудио, загружаем файл без расшифровки:", error);
          // Продолжаем обычную загрузку файла
          const formData = new FormData();
          formData.append("file", file);

          // Логируем userId перед отправкой
          console.log(`🔍 useFileUploads: Отправка файла "${file.name}", userId = ${userId}`);
          axios
            .post("/files/upload/", formData, {
              headers: userId ? { "X-User-ID": userId } : {},
              onUploadProgress: (event) => {
                const pct = event.progress || 0;
                setUploads((prev) => {
                  const next = [...prev];
                  if (next[idx])
                    next[idx] = {
                      ...next[idx],
                      progress: Math.min(Math.round(pct * 100), 95),
                    };
                  return next;
                });
              },
            })
            .then((res) => {
              console.log(`📎 useFileUploads: Файл "${file.name}" успешно загружен:`, res.data);
              setUploads((prev) => {
                const next = [...prev];
                if (next[idx]) {
                  const isImage = res.data?.file_type === 'image';
                  const filePath = res.data?.path || res.data?.image_path;
                  // Для изображений формируем previewUrl из пути (только имя файла, без user_id)
                  const previewUrl = isImage && filePath 
                    ? `/files/${filePath.split('/').pop()}` 
                    : next[idx].previewUrl;
                  next[idx] = { 
                    ...next[idx], 
                    progress: 100, 
                    previewUrl: previewUrl,
                    data: res.data 
                  };
                }
                return next;
              });
            })
            .catch(() => {
              setUploads((prev) => prev.filter((u) => u.file !== file));
            });
        }
      } else {
        // Обычная загрузка для не-аудио файлов
        const formData = new FormData();
        formData.append("file", file);

          // Логируем userId перед отправкой
          console.log(`🔍 useFileUploads: Отправка файла "${file.name}", userId = ${userId}`);
          axios
            .post("/files/upload/", formData, {
              headers: userId ? { "X-User-ID": userId } : {},
              onUploadProgress: (event) => {
              const pct = event.progress || 0;
              setUploads((prev) => {
                const next = [...prev];
                if (next[idx])
                  next[idx] = {
                    ...next[idx],
                    progress: Math.min(Math.round(pct * 100), 95),
                  };
                return next;
              });
            },
          })
          .then((res) => {
            console.log(`📎 useFileUploads: Файл "${file.name}" успешно загружен:`, res.data);
            setUploads((prev) => {
              const next = [...prev];
              if (next[idx]) {
                const isImage = res.data?.file_type === 'image';
                const filePath = res.data?.path || res.data?.image_path;
                // Для изображений формируем previewUrl из пути (только имя файла, без user_id)
                const previewUrl = isImage && filePath 
                  ? `/files/${filePath.split('/').pop()}` 
                  : next[idx].previewUrl;
                next[idx] = { 
                  ...next[idx], 
                  progress: 100, 
                  previewUrl: previewUrl,
                  data: res.data 
                };
              }
              return next;
            });
          })
          .catch(() => {
            setUploads((prev) => prev.filter((u) => u.file !== file));
          });
      }
    }
  };

  const removeUpload = (index: number) => {
    setUploads((prev) => prev.filter((_, i) => i !== index));
  };

  const resetUploads = () => setUploads([]);

  const removeExisting = (index: number) => {
    setExistingFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const items: AttachmentItem[] = useMemo(() => {
    const mappedExisting: AttachmentItem[] = existingFiles.map((f) => {
      const isImage = Boolean(f.file_type === "image");
      return {
        kind: "existing",
        data: f,
        progress: 100,
        previewUrl: isImage ? `/files/${f.path}` : undefined,
        name: !isImage ? f.path.replace(/^files\//, "") : undefined,
      };
    });
    const mappedUploads: AttachmentItem[] = uploads.map((u) => ({
      kind: "upload",
      file: u.file,
      data: u.data,
      progress: u.progress,
      previewUrl: u.previewUrl,
      name: u.file?.name,
      error: u.error,
    }));
    return [...mappedExisting, ...mappedUploads];
  }, [existingFiles, uploads]);

  const removeItem = (index: number) => {
    if (index < existingFiles.length) {
      removeExisting(index);
    } else {
      removeUpload(index - existingFiles.length);
    }
  };

  const getAllFileData = (): FileData[] => {
    const fromUploads = uploads
      .map((u) => u.data)
      .filter((x): x is FileData => Boolean(x));
    return [...existingFiles, ...fromUploads];
  };

  return {
    uploads,
    uploadFiles,
    removeUpload,
    resetUploads,
    setUploads,
    existingFiles,
    setExistingFiles,
    removeExisting,
    items,
    removeItem,
    getAllFileData,
  };
}
