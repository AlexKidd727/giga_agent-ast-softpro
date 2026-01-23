import React, {
  useState,
  useRef,
  useEffect,
  useCallback,
  useMemo,
} from "react";
import { HumanMessage } from "@langchain/langgraph-sdk";
import {
  Check,
  Paperclip,
  Send,
  X,
  Clock,
  Mic,
  Square,
} from "lucide-react";

// Расширенный тип HumanMessage с дополнительными полями
interface HumanMessageWithAdditionalKwargs extends HumanMessage {
  additional_kwargs?: {
    user_input?: string;
    files?: FileData[];
    selected?: any;
  };
}
import { useSettings } from "./Settings.tsx";
import { useFileUpload, UploadedFile } from "../hooks/useFileUploads";
import { useSelectedAttachments } from "../hooks/SelectedAttachmentsContext.tsx";
import { useVoiceRecorder } from "../hooks/useVoiceRecorder";
import {
  AttachmentBubble,
  AttachmentsContainer,
  CircularProgress,
  CloseButton,
  EnlargedImage,
  ImagePreview,
  Overlay,
  ProgressOverlay,
  RemoveButton,
} from "./Attachments.tsx";
import { FileData, GraphState, GraphTemplate } from "../interfaces.ts";
import { BROWSER_USE_NAME } from "../config.ts";
import { UseStream } from "@langchain/langgraph-sdk/react";
import { useRagContext } from "@/components/rag/providers/RAG.tsx";
import Spinner from "./Spinner.tsx";
import { AnimatePresence, motion } from "framer-motion";
import { useAuth } from "./Auth/AuthContext";
import { useUserConfig, useUserId } from "../hooks/useUserConfig";
import { useChatHistory } from "../hooks/useChatHistory";
import { useParams } from "react-router-dom";
import { toast } from "sonner";

const MAX_TEXTAREA_HEIGHT = 200; // макс высота в px

// Прочие стили для превью и оверлея оставляем без изменений...

interface InputAreaProps {
  thread?: UseStream<GraphState, GraphTemplate>;
  onFirstMessage?: (message: string) => void; // Колбэк для сохранения первого сообщения при создании нового чата
}

const InputArea: React.FC<InputAreaProps> = ({ thread, onFirstMessage }) => {
  const [message, setMessage] = useState("");
  const [enlargedImage, setEnlargedImage] = useState<string | null>(null);
  // Тип задачи: "" (пусто), "deferred" (отложенный), "recurring" (регулярный)
  const [taskType, setTaskType] = useState<string>("");
  const [deferredPriority, setDeferredPriority] = useState(0);
  // Параметры для регулярных задач
  const [recurringSchedule, setRecurringSchedule] = useState<string>(""); // Cron expression или интервал
  const [recurringInterval, setRecurringInterval] = useState<string>("daily"); // daily, weekly, monthly, custom
  const [autoSendTranscription, setAutoSendTranscription] = useState(true); // Флажок автоотправки распознанного текста
  const [isAlwaysListening, setIsAlwaysListening] = useState(false); // Флажок постоянного прослушивания
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const { uploads, uploadFiles, removeUpload, resetUploads } = useFileUpload();
  const { selected, clear } = useSelectedAttachments();
  const autoApproveLockRef = useRef<unknown>(null);
  const voiceRecorder = useVoiceRecorder();

  const { collections, activeCollections } = useRagContext();
  const { settings } = useSettings();
  const { user, isAuthenticated } = useAuth();
  const userConfig = useUserConfig();
  const userId = useUserId();
  const { threadId } = useParams<{ threadId?: string }>();
  const { saveChat } = useChatHistory();


  const enabledCollections = useMemo(() => {
    const active = Object.keys(activeCollections).filter(
      (key) => activeCollections[key],
    );
    return collections.filter((collection) => active.includes(collection.uuid));
  }, [activeCollections, collections]);

  // Примечание (MCP, 2026-01-17):
  // Раньше фронт передавал `mcp_tools` и мог вызывать MCP-инструменты из браузера (CORS/proxy).
  // Теперь MCP работает ТОЛЬКО server-side (tool_server загружает инструменты при старте из БД),
  // поэтому фронт не отправляет `mcp_tools` и не делает прямых MCP вызовов.

  const selectedCount = Object.keys(selected).length;

  const isUploading = uploads.some((u) => u.progress < 100 && !u.error);
  // Примечание (MCP, 2026-01-17):
  // Раньше фронт держал локальный флаг isMCPLoading для браузерных MCP вызовов.
  // MCP теперь работает server-side, поэтому оставляем флаг как константу для совместимости UI.
  const isMCPLoading = false;
  
  // Проверка, является ли пользователь админом
  const isAdmin = useMemo(() => {
    return user?.username === "alexis";
  }, [user?.username]);
  
  // Функция для создания отложенной или регулярной задачи
  const createDeferredTask = useCallback(async (content: string) => {
    if (!isAuthenticated || !userId || !isAdmin) {
      return;
    }
    
    try {
      const token = localStorage.getItem("auth_token");
      if (!token) {
        console.error("❌ Токен не найден");
        return;
      }
      
      // Формируем конфигурацию задачи
      const taskConfig: any = {
        files: uploads.map((u) => u.data).filter(Boolean),
        selected: selected,
      };
      
      // Если это регулярная задача, добавляем параметры расписания
      if (taskType === "recurring") {
        taskConfig.recurring = {
          schedule: recurringSchedule,
          interval: recurringInterval,
        };
      }
      
      const response = await fetch("/api/deferred-tasks/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          message: content,
          priority: deferredPriority,
          task_type: taskType, // "deferred" или "recurring"
          task_config: taskConfig,
        }),
      });
      
      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || "Ошибка при создании задачи");
      }
      
      const task = await response.json();
      console.log(`✅ Задача создана (тип: ${taskType}):`, task);
      return task;
    } catch (error) {
      console.error("❌ Ошибка при создании задачи:", error);
      throw error;
    }
  }, [isAuthenticated, userId, isAdmin, deferredPriority, uploads, selected, taskType, recurringSchedule, recurringInterval]);
  const handleSendMessage = useCallback(
    async (content: string, files?: FileData[]) => {
      // Останавливаем постоянное распознавание при отправке сообщения (если активно)
      if (isAlwaysListening && voiceRecorder.isListening) {
        console.log("🎤 Останавливаем постоянное прослушивание при отправке сообщения через handleSendMessage...");
        voiceRecorder.stopContinuousListening();
      }
      
      // Логируем оригинальный контент для отладки
      console.log("🔍 InputArea: Отправка сообщения, оригинальный content:", content);
      console.log("🔍 InputArea: Содержит 'покажи':", content.includes("покажи"));
      console.log("🔍 InputArea: Содержит 'открыть':", content.includes("открыть"));
      
      const newMessage: HumanMessageWithAdditionalKwargs = {
        type: "human",
        content: content,
        additional_kwargs: {
          user_input: content,
          files: files,
          selected: selected,
        },
      };
      console.log("🔍 InputArea: newMessage.content:", newMessage.content);
      console.log("🔍 InputArea: newMessage.additional_kwargs.user_input:", newMessage.additional_kwargs?.user_input);
      console.log("📎 InputArea: Файлы для отправки:", files);
      console.log("📎 InputArea: Количество файлов:", files?.length || 0);
      if (files && files.length > 0) {
        files.forEach((file, idx) => {
          console.log(`📎 InputArea: Файл #${idx + 1}:`, {
            path: file.path,
            file_type: file.file_type,
            size: file.size,
            image_path: file.image_path,
          });
        });
      }
      clear();
      
      // Проверяем, что пользователь аутентифицирован перед отправкой
      if (!isAuthenticated || !userId) {
        console.error("❌ Невозможно отправить сообщение: пользователь не аутентифицирован");
        return;
      }
      
      // ВАЖНО: Всегда передаем configurable с user_id
      // Используем userConfig если доступен, иначе создаем вручную из userId
      const configurable = userConfig?.configurable || {
        user_id: userId,
      };
      
      // Валидация: проверяем, что user_id не пустой и не 'anonymous'
      if (!configurable.user_id || configurable.user_id.trim().toLowerCase() === 'anonymous') {
        console.error(`❌ Невозможно отправить сообщение: невалидный user_id: '${configurable.user_id}'`);
        return;
      }
      
      console.debug(`✅ InputArea: Отправка сообщения с user_id: ${configurable.user_id}`);
      
      // Сохраняем чат при отправке сообщения (если threadId уже существует)
      // Если threadId еще нет, он будет создан в Chat.tsx через onThreadId, и там произойдет сохранение
      if (threadId) {
        // Сохраняем чат с сообщением пользователя
        saveChat(threadId, content);
      } else {
        // Если threadId еще нет, сохраняем первое сообщение для передачи в onThreadId
        onFirstMessage?.(content);
      }
      
      thread?.submit(
        {
          messages: [newMessage],
          collections: enabledCollections,
          secrets: settings.contextSecrets,
          instructions: settings.contextInstructions,
        },
        {
          optimisticValues(prev) {
            const prevMessages = prev.messages ?? [];
            const newMessages = [...prevMessages, newMessage];
            return { ...prev, messages: newMessages };
          },
          streamMode: ["messages"],
          onDisconnect: "continue",
          // @ts-ignore - configurable поддерживается API, но не включен в типы
          configurable: configurable,
        },
      );
    },
    [
      thread,
      selected,
      clear,
      enabledCollections,
      settings.contextInstructions,
      settings.contextSecrets,
      userId,
      isAuthenticated,
      userConfig,
      saveChat,
      threadId,
      isAlwaysListening,
      voiceRecorder,
    ],
  );
  const handleContinueThread = useCallback(
    async (data: any) => {
      // Проверяем, что пользователь аутентифицирован перед продолжением
      if (!isAuthenticated || !userId) {
        console.error("❌ Невозможно продолжить поток: пользователь не аутентифицирован");
        return;
      }
      
      // ВАЖНО: Всегда передаем configurable с user_id
      const configurable = userConfig?.configurable || {
        user_id: userId,
      };
      
      // Валидация: проверяем, что user_id не пустой и не 'anonymous'
      if (!configurable.user_id || configurable.user_id.trim().toLowerCase() === 'anonymous') {
        console.error(`❌ Невозможно продолжить поток: невалидный user_id: '${configurable.user_id}'`);
        return;
      }
      
      // Передаем result напрямую, для других типов используем data
      const resumeData = data.result || data;  // Для других типов используем data как есть
      
      thread?.submit(undefined, {
        command: { resume: resumeData },
        optimisticValues(prev) {
          if (!data.message) return {};
          const prevMessages = prev.messages ?? [];
          const newMessages = [
            ...prevMessages,
            {
              type: "tool",
              content: `"<decline>${data.message}</decline>"`,
            },
          ];
          return { ...prev, messages: newMessages };
        },
        onDisconnect:
          // @ts-ignore
          thread?.messages.at(-1).tool_calls[0]?.name === BROWSER_USE_NAME
            ? "cancel"
            : "continue",
        // @ts-ignore - configurable поддерживается API, но не включен в типы
        configurable: configurable,
      });
    },
    [thread, userId, isAuthenticated, userConfig],
  );

  // автоподгон высоты
  const autoResize = () => {
    const el = textRef.current;
    if (!el) return;
    el.style.height = "auto";
    const newHeight = Math.min(el.scrollHeight, MAX_TEXTAREA_HEIGHT);
    el.style.height = `${newHeight}px`;
  };

  // при первом рендере и при очистке
  useEffect(() => {
    autoResize();
  }, [message]);
  

  const handleContinue = useCallback(
    async (type: "comment" | "approve") => {
      // Примечание (MCP, 2026-01-17):
      // Убрали выполнение MCP tool_call из браузера. Продолжаем поток без клиентского вызова MCP.
      void handleContinueThread({ type, message });
      setMessage("");
    },
    [setMessage, handleContinueThread, message],
  );


  useEffect(() => {
    // Если отладка выключена, автоматически включаем autoApprove
    const effectiveAutoApprove = !settings.debugMode || settings.autoApprove;
    
    // Автоподтверждаем запросы на approve и tool_call (модальные окна для browser_auth убраны)
    
    const canAutoApprove =
      !!thread?.interrupt &&
      ["approve", "tool_call"].includes(thread?.interrupt.value?.type ?? "") &&
      effectiveAutoApprove;

    const interruptKey = thread?.interrupt?.value;

    if (!canAutoApprove) {
      autoApproveLockRef.current = null;
      return;
    }

    if (autoApproveLockRef.current === interruptKey) return;

    if (thread?.isLoading) return;

    autoApproveLockRef.current = interruptKey;
    void handleContinue("approve");
  }, [
    thread?.interrupt,
    thread?.interrupt?.value,
    thread?.isLoading,
    settings.autoApprove,
    settings.debugMode,
    handleContinue,
  ]);

  const handleSend = async () => {
    if (!message.trim() && uploads.length === 0) return;
    
    // Останавливаем постоянное распознавание при отправке запроса (проверяем оба условия)
    if (isAlwaysListening) {
      if (voiceRecorder.isListening) {
        console.log("🎤 Останавливаем постоянное прослушивание при отправке сообщения...");
        voiceRecorder.stopContinuousListening();
      }
    }
    
    // Если выбрана опция "отложенная" или "регулярная" задача и пользователь админ
    if ((taskType === "deferred" || taskType === "recurring") && isAdmin) {
      // Валидация для регулярных задач
      if (taskType === "recurring" && !recurringSchedule.trim()) {
        toast.error("Для регулярной задачи необходимо указать расписание");
        return;
      }
      
      try {
        await createDeferredTask(message);
        setMessage("");
        resetUploads();
        setTaskType("");
        setDeferredPriority(0);
        setRecurringSchedule("");
        setRecurringInterval("daily");
        toast.success(taskType === "recurring" ? "Регулярная задача успешно создана!" : "Отложенная задача успешно создана!");
        return;
      } catch (error) {
        console.error("Ошибка при создании задачи:", error);
        toast.error("Ошибка при создании задачи. Попробуйте еще раз.");
        return;
      }
    }
    
    // Обычная отправка сообщения
    const attachments = uploads.map((u) => u.data).filter(Boolean);
    void handleSendMessage(message, attachments as any);
    setMessage("");
    resetUploads();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!thread?.isLoading && !isUploading) {
        if (thread?.interrupt) {
          void handleContinue(message ? "comment" : "approve");
        } else {
          handleSend();
        }
      }
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      uploadFiles(Array.from(e.target.files));
      e.target.value = "";
    }
  };

  const handleVoiceRecord = async () => {
    // Проверяем доступность STT сервиса
    if (!voiceRecorder.isSTTAvailable) {
      toast.error("Сервис распознавания речи недоступен");
      return;
    }
    
    if (voiceRecorder.isRecording) {
      voiceRecorder.stopRecording();
    } else {
      // Останавливаем постоянное прослушивание перед началом ручной записи
      if (voiceRecorder.isListening) {
        voiceRecorder.stopContinuousListening();
      }
      await voiceRecorder.startRecording();
    }
  };

  // Управление постоянным прослушиванием (новый режим - все распознанное идет в поле ввода)
  useEffect(() => {
    // Не запускаем если STT сервис недоступен
    if (!voiceRecorder.isSTTAvailable) {
      if (isAlwaysListening) {
        setIsAlwaysListening(false);
      }
      return;
    }
    
    if (isAlwaysListening && !voiceRecorder.isListening && !voiceRecorder.isRecording && !voiceRecorder.isProcessing) {
      console.log("🎤 Включаем постоянное распознавание (все слова идут в поле ввода)...");
      // Запускаем режим постоянного распознавания с callback для обработки текста
      voiceRecorder.startContinuousListening((transcribedText: string) => {
        if (!transcribedText || !transcribedText.trim()) return;
        
        console.log("🎤 Распознанный текст в режиме постоянного прослушивания:", transcribedText);
        
        // Проверяем на фразы остановки и отправки
        const actionCheck = voiceRecorder.checkActionWords(transcribedText);
        
        if (actionCheck.found) {
          // Обнаружена фраза типа "выполняй", "действуй", "начинай"
          console.log("🎤 Обнаружена фраза остановки:", actionCheck.word);
          
          // Останавливаем постоянное распознавание
          voiceRecorder.stopContinuousListening();
          
          // Обрезаем текст до фразы остановки
          const trimmedText = voiceRecorder.trimTextToActionWord(transcribedText);
          
          // Формируем финальное сообщение для отправки
          setMessage((prevMessage) => {
            // Объединяем предыдущее сообщение с обрезанным текстом
            const finalMessage = trimmedText && trimmedText.trim() 
              ? (prevMessage ? `${prevMessage} ${trimmedText.trim()}` : trimmedText.trim())
              : prevMessage;
            
            // Автоматически отправляем запрос, если есть текст для отправки
            if (finalMessage && finalMessage.trim()) {
              // Используем setTimeout для асинхронной отправки после обновления состояния
              setTimeout(() => {
                const currentUploads = uploads.map((u) => u.data).filter(Boolean);
                console.log("🎤 Отправляем сообщение по команде голоса:", finalMessage.trim());
                void handleSendMessage(finalMessage.trim(), currentUploads as any);
                setMessage("");
                resetUploads();
                toast.success("Запрос отправлен по команде голоса");
              }, 100);
            } else {
              console.warn("🎤 Ключевое слово найдено, но нет текста для отправки");
              toast.warning("Ключевое слово найдено, но нет текста для отправки");
            }
            
            return finalMessage || prevMessage;
          });
        } else {
          // Обычный распознанный текст - добавляем к сообщению (используем функциональную форму setState)
          setMessage((prevMessage) => {
            return prevMessage ? `${prevMessage} ${transcribedText.trim()}` : transcribedText.trim();
          });
        }
      });
    } else if (!isAlwaysListening && voiceRecorder.isListening) {
      console.log("🎤 Выключаем постоянное распознавание...");
      voiceRecorder.stopContinuousListening();
    }
  }, [isAlwaysListening, voiceRecorder.isListening, voiceRecorder.isRecording, voiceRecorder.isProcessing, voiceRecorder.isSTTAvailable, voiceRecorder, uploads, handleSendMessage, resetUploads]);

  // Обработка завершения записи и расшифровки (для ручной записи, не для постоянного прослушивания)
  useEffect(() => {
    // Запускаем расшифровку когда запись остановлена и есть аудио, но еще не начата обработка
    // И НЕ в режиме постоянного прослушивания (там своя обработка)
    if (voiceRecorder.audioBlob && !voiceRecorder.isRecording && !voiceRecorder.isProcessing && !isAlwaysListening) {
      console.log("🎤 Начинаем расшифровку аудио (ручная запись)...", {
        audioBlobSize: voiceRecorder.audioBlob.size,
        audioBlobType: voiceRecorder.audioBlob.type,
        autoSend: autoSendTranscription,
      });
      
      const processRecording = async () => {
        try {
          let transcribedText = await voiceRecorder.transcribeAudio(voiceRecorder.audioBlob!);
          console.log("🎤 Результат расшифровки:", transcribedText);
          
          // Проверяем на наличие ключевых слов действий и обрезаем текст до них
          if (transcribedText) {
            const actionCheck = voiceRecorder.checkActionWords(transcribedText);
            if (actionCheck.found) {
              console.log(`🎤 Обнаружено ключевое слово '${actionCheck.word}', обрезаем текст...`);
              transcribedText = voiceRecorder.trimTextToActionWord(transcribedText);
              console.log("🎤 Текст после обрезки:", transcribedText);
              toast.info(`Запись остановлена по команде '${actionCheck.word}'`);
            }
          }
          
          if (transcribedText && transcribedText.trim()) {
            // Если включена автоотправка, сразу отправляем сообщение
            if (autoSendTranscription) {
              console.log("🎤 Автоотправка включена, отправляем сообщение...");
              toast.success("Речь распознана и отправлена");
              // Отправляем распознанный текст сразу
              const attachments = uploads.map((u) => u.data).filter(Boolean);
              void handleSendMessage(transcribedText, attachments as any);
              setMessage("");
              resetUploads();
            } else {
              // Добавляем расшифрованный текст к сообщению
              const newMessage = message ? `${message}\n${transcribedText}` : transcribedText;
              setMessage(newMessage);
              console.log("🎤 Текст добавлен к сообщению:", newMessage);
              toast.success("Речь распознана и добавлена к сообщению");
            }
          } else {
            console.warn("🎤 Расшифровка вернула пустой текст");
            toast.warning("Не удалось распознать речь. Попробуйте еще раз.");
          }
        } catch (error) {
          console.error("🎤 Ошибка при расшифровке:", error);
          toast.error("Ошибка при распознавании речи");
        } finally {
          // Сбрасываем состояние после обработки
          voiceRecorder.reset();
        }
      };
      
      void processRecording();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voiceRecorder.audioBlob, voiceRecorder.isRecording, voiceRecorder.isProcessing, autoSendTranscription, isAlwaysListening]);

  return (
    <div className="p-4 bg-card dark:bg-input border-border rounded-lg shadow-[2px_2px_12px_6px_rgba(0,0,0,0.04)] dark:shadow-[2px_2px_12px_6px_rgba(0,0,0,0.14)] print:hidden border-t-1 border-highlight">
      <input
        className="hidden"
        type="file"
        ref={fileInputRef}
        onChange={handleFileChange}
        multiple
        disabled={thread?.isLoading || isMCPLoading || voiceRecorder.isRecording || voiceRecorder.isProcessing}
      />
      {/* Кнопки и флажки над текстовым полем */}
      <div className="flex items-center gap-2 mb-2">
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={thread?.isLoading || isMCPLoading || voiceRecorder.isRecording || voiceRecorder.isProcessing}
          title="Добавить вложения"
          className="w-9 h-9 p-0 rounded-full text-foreground flex items-center justify-center transition-colors cursor-pointer outline-hidden disabled:opacity-67 hover:bg-accent"
        >
          <Paperclip className="w-4 h-4" />
        </button>
        {/* Кнопка записи голоса - показываем только если STT сервис доступен */}
        {voiceRecorder.isSTTAvailable && (
          <button
            type="button"
            onClick={handleVoiceRecord}
            disabled={thread?.isLoading || isMCPLoading || voiceRecorder.isProcessing}
            title={voiceRecorder.isRecording ? "Остановить запись" : "Записать голосовое сообщение"}
            className={`w-9 h-9 p-0 rounded-full flex items-center justify-center transition-colors cursor-pointer outline-hidden disabled:opacity-67 ${
              voiceRecorder.isRecording 
                ? "bg-red-500 text-white animate-pulse" 
                : "text-foreground hover:bg-accent"
            }`}
          >
            {voiceRecorder.isRecording ? <Square className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
          </button>
        )}
        {/* Флажок автоотправки распознанного текста - показываем только если STT доступен */}
        {voiceRecorder.isSTTAvailable && (
          <label className="flex items-center gap-1.5 cursor-pointer text-xs text-muted-foreground hover:text-foreground transition-colors">
            <input
              type="checkbox"
              checked={autoSendTranscription}
              onChange={(e) => setAutoSendTranscription(e.target.checked)}
              className="w-3.5 h-3.5 rounded border-gray-300 dark:border-gray-600 cursor-pointer"
              title="Автоматически отправлять распознанный текст"
            />
            <span className="select-none">Автоотправка</span>
          </label>
        )}
        {/* Флажок постоянного прослушивания - показываем только если STT доступен */}
        {voiceRecorder.isSTTAvailable && (
          <label className="flex items-center gap-1.5 cursor-pointer text-xs text-muted-foreground hover:text-foreground transition-colors">
            <input
              type="checkbox"
              checked={isAlwaysListening}
              onChange={(e) => setIsAlwaysListening(e.target.checked)}
              className="w-3.5 h-3.5 rounded border-gray-300 dark:border-gray-600 cursor-pointer"
              title="Слушать постоянно (все распознанные слова идут в поле ввода, остановка при отправке или фразах 'выполняй', 'действуй', 'начинай')"
              disabled={voiceRecorder.isRecording || voiceRecorder.isProcessing}
            />
            <span className="select-none">Слушать постоянно</span>
          </label>
        )}
        {/* Выпадающий список типа задачи для админа */}
        {isAdmin && (
          <div className="flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5 text-muted-foreground" />
            <select
              value={taskType}
              onChange={(e) => setTaskType(e.target.value)}
              className="text-xs px-2 py-0.5 rounded border border-gray-300 dark:border-gray-600 bg-background text-foreground cursor-pointer"
              title="Выберите тип задачи"
            >
              <option value="">Обычная</option>
              <option value="deferred">Отложенный</option>
              <option value="recurring">Регулярный</option>
            </select>
          </div>
        )}
        {/* Поле приоритета для отложенной/регулярной задачи */}
        {isAdmin && (taskType === "deferred" || taskType === "recurring") && (
          <div className="flex items-center gap-1">
            <label className="text-xs text-muted-foreground">Приоритет:</label>
            <input
              type="number"
              min="0"
              max="100"
              value={deferredPriority}
              onChange={(e) => setDeferredPriority(parseInt(e.target.value) || 0)}
              className="w-12 px-1.5 py-0.5 text-xs rounded border border-gray-300 dark:border-gray-600 bg-background"
            />
          </div>
        )}
        {/* Поля для настройки регулярности */}
        {isAdmin && taskType === "recurring" && (
          <div className="flex items-center gap-2 flex-wrap">
            <div className="flex items-center gap-1">
              <label className="text-xs text-muted-foreground">Интервал:</label>
              <select
                value={recurringInterval}
                onChange={(e) => {
                  setRecurringInterval(e.target.value);
                  // Устанавливаем примеры расписания в зависимости от интервала
                  const examples: Record<string, string> = {
                    daily: "0 9 * * *", // Каждый день в 9:00
                    weekly: "0 9 * * 1", // Каждый понедельник в 9:00
                    monthly: "0 9 1 * *", // Первое число каждого месяца в 9:00
                    custom: "",
                  };
                  if (e.target.value !== "custom") {
                    setRecurringSchedule(examples[e.target.value]);
                  } else {
                    setRecurringSchedule("");
                  }
                }}
                className="text-xs px-2 py-0.5 rounded border border-gray-300 dark:border-gray-600 bg-background text-foreground cursor-pointer"
              >
                <option value="daily">Ежедневно</option>
                <option value="weekly">Еженедельно</option>
                <option value="monthly">Ежемесячно</option>
                <option value="custom">Свой (cron)</option>
              </select>
            </div>
            <div className="flex items-center gap-1">
              <label className="text-xs text-muted-foreground">Расписание:</label>
              <input
                type="text"
                value={recurringSchedule}
                onChange={(e) => setRecurringSchedule(e.target.value)}
                placeholder="0 9 * * *"
                className="w-24 px-1.5 py-0.5 text-xs rounded border border-gray-300 dark:border-gray-600 bg-background"
                title="Cron выражение (например: 0 9 * * * для ежедневно в 9:00)"
              />
            </div>
          </div>
        )}
      </div>

      {/* Текстовое поле и кнопка отправки */}
      <div className="flex items-end gap-2 relative">
        <textarea
          placeholder={
            thread?.interrupt
              ? "Принять / Отменить с комментарием…"
              : "Введите вашу задачу…"
          }
          ref={textRef}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={thread?.isLoading || isMCPLoading}
          className="flex-1 min-h-[76px] max-h-[200px] resize-none font-sans p-3 rounded-md text-foreground placeholder:text-muted-foreground overflow-y-auto outline-none border-0 disabled:opacity-60"
        />
        {thread?.interrupt &&
        thread?.interrupt.value &&
        ["approve", "tool_call"].includes(thread.interrupt.value.type) &&
        settings.debugMode && // Показываем кнопки только в режиме отладки
        (!settings.autoApprove ||
          thread.interrupt.value.type === "tool_call") ? (
          <>
            {isMCPLoading ? (
              <div className="w-9 h-9 flex items-center justify-center">
                <Spinner size="16" />
              </div>
            ) : (
              <>
                <motion.div layout className="flex items-center gap-2">
                  <motion.button
                    layout
                    transition={{ type: "spring", stiffness: 500, damping: 35 }}
                    onClick={() => handleContinue("comment")}
                    disabled={thread.isLoading || isMCPLoading}
                    title="Отменить выполнение"
                    className="w-9 h-9 p-0 rounded-full bg-red-600 text-white flex items-center justify-center transition-colors hover:bg-red-700 disabled:opacity-67"
                  >
                    <X />
                  </motion.button>
                  <AnimatePresence mode="popLayout">
                    {!message.trim() && (
                      <motion.button
                        key="approve-btn"
                        layout
                        initial={{ x: 24, scale: 1, opacity: 1 }}
                        animate={{ x: 0, scale: 1, opacity: 1 }}
                        exit={{ x: 24, scale: 1, opacity: 1 }}
                        transition={{
                          type: "spring",
                          stiffness: 500,
                          damping: 35,
                        }}
                        onClick={() => handleContinue("approve")}
                        disabled={thread.isLoading || isMCPLoading}
                        title="Подтвердить выполнение"
                        className="w-9 h-9 p-0 rounded-full bg-green-600 text-white flex items-center justify-center transition-colors hover:bg-green-700 disabled:opacity-67"
                      >
                        <Check />
                      </motion.button>
                    )}
                  </AnimatePresence>
                </motion.div>
              </>
            )}
          </>
        ) : (
          <button
            type="button"
            onClick={handleSend}
            disabled={
              thread?.isLoading ||
              isMCPLoading ||
              !message.trim() ||
              isUploading
            }
            title="Отправить"
            className="w-9 h-9 p-0 rounded-full text-foreground flex items-center justify-center transition-colors cursor-pointer outline-hidden disabled:opacity-67"
          >
            <Send />
          </button>
        )}
      </div>

      {uploads.length > 0 && (
        <AttachmentsContainer>
          {uploads.map((u: UploadedFile, idx) => {
            // Получаем имя файла из разных источников
            // Приоритет: u.data?.name (из ответа сервера) > u.file?.name (из File объекта) > извлечение из path > 'Файл'
            const fileName = u.data?.name || u.file?.name || u.data?.path?.split('/').pop() || u.data?.path || 'Файл';
            const isImage = Boolean(u.previewUrl || u.data?.file_type === 'image');
            const isAudio = u.file?.type.startsWith("audio/") || 
              /\.(wav|mp3|flac|ogg|webm|m4a)$/i.test(fileName);
            const transcribedText = (u.data as any)?.transcribed_text;
            
            return (
              <AttachmentBubble
                key={idx}
                onClick={() => u.previewUrl && setEnlargedImage(u.previewUrl!)}
              >
                {isImage && u.previewUrl ? (
                  <ImagePreview src={u.previewUrl} />
                ) : null}
                
                {/* Показываем название файла и расшифровку для аудио */}
                <div className="flex flex-col gap-1">
                  <span style={{ 
                    maxWidth: isImage ? '120px' : '200px', 
                    overflow: 'hidden', 
                    textOverflow: 'ellipsis', 
                    whiteSpace: 'nowrap',
                    fontSize: '13px'
                  }}>
                    {fileName}
                  </span>
                  {isAudio && transcribedText && (
                    <span style={{
                      fontSize: '11px',
                      color: 'var(--muted-foreground)',
                      fontStyle: 'italic',
                      maxWidth: '200px',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    }}>
                      🎤 {transcribedText}
                    </span>
                  )}
                </div>

                {u.progress < 100 && (
                  <ProgressOverlay>
                    <CircularProgress progress={u.progress}>
                      {u.progress}%
                    </CircularProgress>
                  </ProgressOverlay>
                )}

                <RemoveButton
                  onClick={(e) => {
                    e.stopPropagation();
                    removeUpload(idx);
                  }}
                >
                  ×
                </RemoveButton>
              </AttachmentBubble>
            );
          })}
        </AttachmentsContainer>
      )}

      {/* Индикаторы голосовых функций - показываем только если STT доступен */}
      {voiceRecorder.isSTTAvailable && (
        <>
          {/* Индикатор записи голоса */}
          {voiceRecorder.isRecording && (
            <div className="mt-2 flex items-center gap-2 text-sm text-red-500">
              <div className="w-2 h-2 bg-red-500 rounded-full animate-pulse" />
              <span>Идет запись...</span>
            </div>
          )}
          {voiceRecorder.isProcessing && (
            <div className="mt-2 flex items-center gap-2 text-sm text-blue-500">
              <Spinner size="16" />
              <span>Распознавание речи...</span>
            </div>
          )}
          {/* Индикатор постоянного прослушивания */}
          {voiceRecorder.isListening && !voiceRecorder.isRecording && !voiceRecorder.isProcessing && isAlwaysListening && (
            <div className="mt-2 flex items-center gap-2 text-sm text-green-500">
              <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
              <span>Слушаю постоянно... Все распознанные слова идут в поле ввода. Скажите "выполняй", "действуй" или "начинай" для отправки запроса.</span>
            </div>
          )}
        </>
      )}


      <div
        className={[
          "absolute bottom-2 left-[75px] text-muted-foreground text-xs pointer-events-none transition-opacity duration-100",
          selectedCount > 0
            ? "opacity-100 translate-y-0"
            : "opacity-0 translate-y-1",
        ].join(" ")}
      >
        Выбрано вложений: {selectedCount}
      </div>

      {enlargedImage && (
        <Overlay onClick={() => setEnlargedImage(null)}>
          <EnlargedImage src={enlargedImage} />
          <CloseButton onClick={() => setEnlargedImage(null)}>×</CloseButton>
        </Overlay>
      )}
      
    </div>
  );
};

export default InputArea;
