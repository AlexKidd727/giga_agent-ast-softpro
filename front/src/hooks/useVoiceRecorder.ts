import { useState, useRef, useCallback, useEffect } from "react";
import { toast } from "sonner";

export interface VoiceRecorderState {
  isRecording: boolean;
  isProcessing: boolean;
  audioBlob: Blob | null;
  error: string | null;
  isListening: boolean; // Флаг постоянного прослушивания
  isSTTAvailable: boolean; // Флаг доступности STT сервиса
  isCheckingSTT: boolean; // Флаг проверки доступности STT
}

const STT_SERVICE_URL = import.meta.env.VITE_STT_SERVICE_URL || "/stt";
const ACTION_WORDS = ["начни выполнять", "приступай", "делай", "выполняй", "действуй", "начинай"]; // Фразы для остановки и отправки запроса
const CHUNK_SAMPLES = 2400; // Размер чанка в сэмплах (300ms * 8kHz)
const CHUNK_BYTES = CHUNK_SAMPLES * 2; // Размер чанка в байтах (16-bit PCM)
const MAX_OUTSTANDING = 3; // Максимальное количество необработанных чанков
const MAX_BACKLOG_SEC = 3; // Максимальная задержка в секундах

export function useVoiceRecorder() {
  const [state, setState] = useState<VoiceRecorderState>({
    isRecording: false,
    isProcessing: false,
    audioBlob: null,
    error: null,
    isListening: false,
    isSTTAvailable: false, // По умолчанию недоступен, пока не проверим
    isCheckingSTT: true, // Изначально проверяем
  });

  // Проверка доступности STT сервиса при монтировании
  useEffect(() => {
    const checkSTTAvailability = async () => {
      try {
        // Пробуем сделать health check к STT сервису
        const response = await fetch(`${STT_SERVICE_URL}/health`, {
          method: "GET",
          signal: AbortSignal.timeout(5000), // Таймаут 5 секунд
        });
        
        if (response.ok) {
          console.log("STT сервис доступен");
          setState((prev) => ({ ...prev, isSTTAvailable: true, isCheckingSTT: false }));
        } else {
          console.warn("STT сервис недоступен (HTTP ошибка):", response.status);
          setState((prev) => ({ ...prev, isSTTAvailable: false, isCheckingSTT: false }));
        }
      } catch (error) {
        console.warn("STT сервис недоступен:", error);
        setState((prev) => ({ ...prev, isSTTAvailable: false, isCheckingSTT: false }));
      }
    };

    checkSTTAvailability();
    
    // Периодически проверяем доступность STT (каждые 30 секунд)
    const intervalId = setInterval(checkSTTAvailability, 30000);
    
    return () => clearInterval(intervalId);
  }, []);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const recordingCheckIntervalRef = useRef<number | null>(null);
  const recordingStreamRef = useRef<MediaStream | null>(null);
  const recentChunksRef = useRef<Blob[]>([]); // Храним последние сегменты для проверки
  const lastCheckTimeRef = useRef<number>(0);
  const continuousListeningRef = useRef<boolean>(false); // Флаг режима постоянного распознавания
  const onTranscribedTextRef = useRef<((text: string) => void) | null>(null); // Callback для передачи распознанного текста
  const wsRef = useRef<WebSocket | null>(null); // WebSocket соединение для стриминга
  const audioContextRef = useRef<AudioContext | null>(null); // AudioContext для обработки аудио
  const processorRef = useRef<ScriptProcessorNode | null>(null); // ScriptProcessorNode для обработки аудио
  const mediaStreamRef = useRef<MediaStream | null>(null); // MediaStream для микрофона
  const outstandingRef = useRef<number>(0); // Количество необработанных чанков
  const backlogCheckRef = useRef<number | null>(null); // Интервал проверки задержки
  const buffer8kRef = useRef<number[]>([]); // Буфер для накопления аудио данных

  const transcribeAudio = useCallback(async (audioBlob: Blob): Promise<string | null> => {
    console.log("🎤 transcribeAudio вызван", {
      blobSize: audioBlob.size,
      blobType: audioBlob.type,
      sttUrl: STT_SERVICE_URL,
    });
    
    setState((prev) => ({ ...prev, isProcessing: true, error: null }));

    try {
      const formData = new FormData();
      // Используем правильное имя файла в зависимости от типа
      const fileName = audioBlob.type.includes("webm") 
        ? "recording.webm" 
        : audioBlob.type.includes("ogg")
        ? "recording.ogg"
        : "recording.wav";
      formData.append("file", audioBlob, fileName);

      console.log("🎤 Отправка запроса на", `${STT_SERVICE_URL}/api/transcribe`);

      const response = await fetch(`${STT_SERVICE_URL}/api/transcribe`, {
        method: "POST",
        body: formData,
      });

      console.log("🎤 Ответ получен:", response.status, response.statusText);

      if (!response.ok) {
        const errorText = await response.text();
        console.error("🎤 Ошибка HTTP:", response.status, errorText);
        throw new Error(`HTTP error! status: ${response.status}, message: ${errorText}`);
      }

      const result = await response.json();
      console.log("🎤 Результат распознавания:", result);
      
      setState((prev) => ({ ...prev, isProcessing: false }));
      
      const text = result.text || null;
      if (!text || !text.trim()) {
        console.warn("🎤 Распознанный текст пуст");
      }
      
      return text;
    } catch (error) {
      console.error("🎤 Ошибка при расшифровке аудио:", error);
      setState((prev) => ({
        ...prev,
        isProcessing: false,
        error: "Ошибка распознавания речи",
      }));
      toast.error("Ошибка распознавания речи");
      return null;
    }
  }, []);

  const reset = useCallback(() => {
    setState((prev) => ({
      ...prev,
      isRecording: false,
      isProcessing: false,
      audioBlob: null,
      error: null,
    }));
    audioChunksRef.current = [];
  }, []);

  // Проверка на фразы остановки и отправки ("выполняй", "действуй", "начинай")
  const checkActionWords = useCallback((text: string): { found: boolean; word: string | null } => {
    if (!text) return { found: false, word: null };
    const normalizedText = text.toLowerCase().trim();
    
    // Разбиваем текст на слова для более точного поиска
    const words = normalizedText.split(/\s+/);
    
    for (const actionWord of ACTION_WORDS) {
      const actionWordLower = actionWord.toLowerCase();
      // Проверяем как целое слово, так и вхождение в текст (для случаев с опечатками)
      const foundAsWord = words.some(word => word === actionWordLower || word.startsWith(actionWordLower));
      const foundInText = normalizedText.includes(actionWordLower);
      
      if (foundAsWord || foundInText) {
        console.log(`🎤 Ключевое слово "${actionWord}" найдено в тексте: "${text}"`);
        return { found: true, word: actionWord };
      }
    }
    
    return { found: false, word: null };
  }, []);

  // Обрезка текста до action word (исключая само слово)
  const trimTextToActionWord = useCallback((text: string): string => {
    if (!text) return text;
    const normalizedText = text.toLowerCase();
    let actionIndex = -1;
    let actionWord = "";
    
    for (const word of ACTION_WORDS) {
      const index = normalizedText.indexOf(word.toLowerCase());
      if (index !== -1 && (actionIndex === -1 || index < actionIndex)) {
        actionIndex = index;
        actionWord = word;
      }
    }
    
    if (actionIndex !== -1) {
      // Обрезаем текст до action word (исключая само слово)
      return text.substring(0, actionIndex).trim();
    }
    
    return text;
  }, []);

  // Функция для периодической проверки записи на наличие ключевых слов действий
  const checkRecordingForActionWords = useCallback(async () => {
    if (!mediaRecorderRef.current || !state.isRecording) {
      return;
    }

    try {
      // Проверяем последние сегменты (последние 3-4 секунды)
      if (recentChunksRef.current.length === 0) {
        return;
      }

      // Объединяем последние сегменты для проверки
      const checkBlob = new Blob(recentChunksRef.current, { 
        type: mediaRecorderRef.current.mimeType 
      });
      
      if (checkBlob.size === 0) {
        return;
      }

      const transcribedText = await transcribeAudio(checkBlob);
      if (transcribedText) {
        const actionCheck = checkActionWords(transcribedText);
        if (actionCheck.found) {
          console.log(`🎤 Обнаружено ключевое слово '${actionCheck.word}' во время записи, останавливаем запись...`);
          // Останавливаем основную запись
          if (mediaRecorderRef.current && state.isRecording) {
            mediaRecorderRef.current.stop();
          }
          // Очищаем интервал проверки
          if (recordingCheckIntervalRef.current) {
            clearInterval(recordingCheckIntervalRef.current);
            recordingCheckIntervalRef.current = null;
          }
          toast.info(`Запись остановлена по команде '${actionCheck.word}'`);
        } else {
          // Очищаем проверенные сегменты, оставляем только последний для следующей проверки
          if (recentChunksRef.current.length > 1) {
            recentChunksRef.current = recentChunksRef.current.slice(-1);
          }
        }
      }
    } catch (error) {
      console.error("Error checking recording for action words:", error);
      // Продолжаем запись даже при ошибке проверки
    }
  }, [state.isRecording, transcribeAudio, checkActionWords]);

  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      recordingStreamRef.current = stream;
      const mediaRecorder = new MediaRecorder(stream, {
        mimeType: MediaRecorder.isTypeSupported("audio/webm") 
          ? "audio/webm" 
          : MediaRecorder.isTypeSupported("audio/ogg") 
          ? "audio/ogg" 
          : "audio/wav",
      });

      audioChunksRef.current = [];
      recentChunksRef.current = [];
      lastCheckTimeRef.current = Date.now();
      
      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
          // Сохраняем последние сегменты для проверки на ключевые слова действий
          recentChunksRef.current.push(event.data);
          // Ограничиваем размер буфера последних сегментов (примерно последние 4-5 секунд)
          // Если сегментов слишком много, удаляем старые
          if (recentChunksRef.current.length > 3) {
            recentChunksRef.current.shift();
          }
        }
      };

      mediaRecorder.onstop = () => {
        const audioBlob = new Blob(audioChunksRef.current, { 
          type: mediaRecorder.mimeType 
        });
        setState((prev) => ({ ...prev, audioBlob, isRecording: false }));
        stream.getTracks().forEach((track) => track.stop());
        recordingStreamRef.current = null;
        // Очищаем интервал проверки при остановке записи
        if (recordingCheckIntervalRef.current) {
          clearInterval(recordingCheckIntervalRef.current);
          recordingCheckIntervalRef.current = null;
        }
        // Очищаем буфер последних сегментов
        recentChunksRef.current = [];
      };

      mediaRecorder.onerror = (event) => {
        console.error("MediaRecorder error:", event);
        setState((prev) => ({
          ...prev,
          error: "Ошибка записи аудио",
          isRecording: false,
        }));
        stream.getTracks().forEach((track) => track.stop());
        recordingStreamRef.current = null;
        // Очищаем интервал проверки при ошибке
        if (recordingCheckIntervalRef.current) {
          clearInterval(recordingCheckIntervalRef.current);
          recordingCheckIntervalRef.current = null;
        }
        // Очищаем буфер последних сегментов
        recentChunksRef.current = [];
      };

      mediaRecorderRef.current = mediaRecorder;
      // Запускаем запись с timeslice для получения сегментов каждые 2 секунды
      mediaRecorder.start(2000);
      setState((prev) => ({ ...prev, isRecording: true, error: null, audioBlob: null }));
      
      // Запускаем периодическую проверку на наличие ключевых слов действий каждые 3 секунды
      recordingCheckIntervalRef.current = window.setInterval(() => {
        if (state.isRecording && recentChunksRef.current.length > 0) {
          void checkRecordingForActionWords();
        }
      }, 3000);
    } catch (error) {
      console.error("Error starting recording:", error);
      setState((prev) => ({
        ...prev,
        error: "Не удалось получить доступ к микрофону",
        isRecording: false,
      }));
      toast.error("Не удалось получить доступ к микрофону");
    }
  }, [checkRecordingForActionWords, state.isRecording]);

  const stopRecording = useCallback(() => {
    // Очищаем интервал проверки при ручной остановке
    if (recordingCheckIntervalRef.current) {
      clearInterval(recordingCheckIntervalRef.current);
      recordingCheckIntervalRef.current = null;
    }
    // Очищаем буфер последних сегментов
    recentChunksRef.current = [];
    if (mediaRecorderRef.current && state.isRecording) {
      mediaRecorderRef.current.stop();
    }
  }, [state.isRecording]);

  // Конвертация float32 в PCM16 (как в T-one)
  const floatToPCM16 = useCallback((floatBuf: Float32Array): Int16Array => {
    const pcm = new Int16Array(floatBuf.length);
    for (let i = 0; i < floatBuf.length; i++) {
      const s = Math.max(-1, Math.min(1, floatBuf[i]));
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    return pcm;
  }, []);

  // Построение URL для WebSocket
  const buildWsUrl = useCallback((): string => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = STT_SERVICE_URL.replace(/^https?:\/\//, "").replace(/^wss?:\/\//, "");
    return `${protocol}//${host}/api/ws`;
  }, []);

  // Остановка постоянного распознавания
  const stopContinuousListening = useCallback(() => {
    continuousListeningRef.current = false;
    onTranscribedTextRef.current = null;

    // Останавливаем проверку задержки
    if (backlogCheckRef.current) {
      clearInterval(backlogCheckRef.current);
      backlogCheckRef.current = null;
    }

    // Закрываем WebSocket соединение
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      // Отправляем пустой чанк для завершения потока (как в T-one)
      wsRef.current.send(new Uint8Array());
      wsRef.current.close();
    }
    wsRef.current = null;

    // Останавливаем обработку аудио
    if (processorRef.current) {
      processorRef.current.disconnect();
      (processorRef.current as any).onaudioprocess = null;
      processorRef.current = null;
    }

    // Закрываем AudioContext
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }

    // Останавливаем поток микрофона
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }

    // Очищаем буфер
    buffer8kRef.current = [];
    outstandingRef.current = 0;

    setState((prev) => ({ ...prev, isListening: false }));
    console.log("🎤 Постоянное прослушивание остановлено");
  }, []);

  // Функция постоянного распознавания через WebSocket стриминг (как в T-one)
  const startContinuousListening = useCallback(async (onTranscribedText: (text: string) => void) => {
    if (continuousListeningRef.current) return;

    continuousListeningRef.current = true;
    onTranscribedTextRef.current = onTranscribedText;
    setState((prev) => ({ ...prev, isListening: true }));

    try {
      // Получаем доступ к микрофону
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
        video: false,
      });
      mediaStreamRef.current = stream;

      // Создаем AudioContext с частотой дискретизации 8kHz (как в T-one)
      const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)({ sampleRate: 8000 });
      audioContextRef.current = audioCtx;

      const input = audioCtx.createMediaStreamSource(stream);
      // Используем ScriptProcessorNode для обработки аудио (как в T-one)
      const processor = (audioCtx.createScriptProcessor || (audioCtx as any).createJavaScriptNode).call(
        audioCtx,
        1024,
        1,
        1
      );
      processorRef.current = processor;
      input.connect(processor);
      processor.connect(audioCtx.destination);

      // Инициализируем WebSocket соединение
      const wsUrl = buildWsUrl();
      console.log("🎤 Подключение к WebSocket:", wsUrl);
      const ws = new WebSocket(wsUrl);
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;
      outstandingRef.current = 0;

      // Обработка сообщений от сервера
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          if (msg.event === "ready") {
            outstandingRef.current = Math.max(outstandingRef.current - 1, 0);
          } else if (msg.event === "transcript") {
            const phrase = msg.phrase;
            if (phrase && phrase.text && phrase.text.trim()) {
              const transcribedText = phrase.text.trim();
              console.log("🎤 Распознанный текст в реальном времени:", transcribedText);

              // Проверяем на фразы остановки
              const actionCheck = checkActionWords(transcribedText);

              if (actionCheck.found) {
                // Обнаружена фраза остановки, обрезаем текст и передаем в callback
                console.log("🎤 В useVoiceRecorder: обнаружено ключевое слово:", actionCheck.word);
                const trimmedText = trimTextToActionWord(transcribedText);
                // Передаем обрезанный текст в callback
                if (trimmedText && trimmedText.trim()) {
                  onTranscribedText(trimmedText.trim());
                } else {
                  // Если обрезанный текст пустой, передаем пустую строку для триггера отправки
                  onTranscribedText("");
                }
                // Останавливаем постоянное распознавание
                stopContinuousListening();
                return;
              } else {
                // Передаем распознанный текст в callback
                onTranscribedText(transcribedText);
              }
            }
          }
        } catch (err) {
          console.error("🎤 Ошибка парсинга сообщения WebSocket:", err);
        }
      };

      ws.onerror = (e) => {
        console.error("🎤 WebSocket error:", e);
        setState((prev) => ({ ...prev, error: "Ошибка WebSocket соединения" }));
        toast.error("Ошибка соединения с сервером распознавания");
      };

      ws.onclose = () => {
        console.log("🎤 WebSocket закрыт");
        if (continuousListeningRef.current) {
          // Переподключаемся, если режим прослушивания все еще активен
          setTimeout(() => {
            if (continuousListeningRef.current) {
              console.log("🎤 Переподключение к WebSocket...");
              startContinuousListening(onTranscribedText);
            }
          }, 1000);
        }
      };

      // Обработка аудио данных в реальном времени
      buffer8kRef.current = [];
      processor.onaudioprocess = (ev) => {
        if (!continuousListeningRef.current || !ws || ws.readyState !== WebSocket.OPEN) {
          return;
        }

        const data = ev.inputBuffer.getChannelData(0);
        buffer8kRef.current.push(...Array.from(data));

        // Отправляем чанки когда накопилось достаточно данных
        while (buffer8kRef.current.length >= CHUNK_SAMPLES && outstandingRef.current < MAX_OUTSTANDING) {
          const chunk = buffer8kRef.current.slice(0, CHUNK_SAMPLES);
          buffer8kRef.current = buffer8kRef.current.slice(CHUNK_SAMPLES);
          const pcm16 = floatToPCM16(new Float32Array(chunk));
          ws.send(new Uint8Array(pcm16.buffer));
          outstandingRef.current++;
        }
      };

      // Проверка задержки (как в T-one)
      backlogCheckRef.current = window.setInterval(() => {
        const lagSec = outstandingRef.current * 0.3;
        if (lagSec > MAX_BACKLOG_SEC) {
          console.warn(`🎤 Сервер отстает более чем на ${MAX_BACKLOG_SEC} секунд`);
          stopContinuousListening();
          toast.warning(`Сервер отстает более чем на ${MAX_BACKLOG_SEC} секунд. Остановка прослушивания.`);
        }
      }, 1000);

      // Ждем открытия WebSocket
      await new Promise<void>((resolve, reject) => {
        if (ws.readyState === WebSocket.OPEN) {
          resolve();
        } else {
          ws.onopen = () => resolve();
          ws.onerror = (e) => reject(e);
        }
      });

      console.log("🎤 Постоянное прослушивание запущено через WebSocket");
    } catch (error) {
      console.error("🎤 Ошибка при запуске постоянного прослушивания:", error);
      setState((prev) => ({
        ...prev,
        error: "Не удалось запустить постоянное прослушивание",
        isListening: false,
      }));
      toast.error("Не удалось запустить постоянное прослушивание");
      stopContinuousListening();
    }
  }, [buildWsUrl, floatToPCM16, checkActionWords, trimTextToActionWord, stopContinuousListening]);

  // Очистка при размонтировании
  useEffect(() => {
    return () => {
      stopContinuousListening();
      // Очищаем интервал проверки записи
      if (recordingCheckIntervalRef.current) {
        clearInterval(recordingCheckIntervalRef.current);
        recordingCheckIntervalRef.current = null;
      }
      // Останавливаем поток записи
      if (recordingStreamRef.current) {
        recordingStreamRef.current.getTracks().forEach((track) => track.stop());
        recordingStreamRef.current = null;
      }
      // Очищаем буфер последних сегментов
      recentChunksRef.current = [];
      // Закрываем WebSocket если он открыт
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.close();
      }
      // Останавливаем проверку задержки
      if (backlogCheckRef.current) {
        clearInterval(backlogCheckRef.current);
        backlogCheckRef.current = null;
      }
    };
  }, [stopContinuousListening]);

  return {
    ...state,
    startRecording,
    stopRecording,
    transcribeAudio,
    reset,
    startContinuousListening,
    stopContinuousListening,
    checkActionWords,
    trimTextToActionWord,
  };
}

