import React, { useEffect, useState, useCallback } from "react";
import { Cpu, RefreshCw, ChevronDown } from "lucide-react";
import { useUserId } from "../hooks/useUserConfig";
import { useAuth } from "./Auth/AuthContext";
import { Badge } from "./ui/badge";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "./ui/dropdown-menu";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "./ui/alert-dialog";
import { toast } from "sonner";

const API_BASE = "/api";

interface ModelInfo {
  model: string;
  displayName: string;
  provider?: string;
}

// Глобальное событие для обновления модели
const MODEL_UPDATE_EVENT = "model-info-update";

// Функция для триггера обновления модели извне
export const triggerModelUpdate = () => {
  window.dispatchEvent(new CustomEvent(MODEL_UPDATE_EVENT));
};

const ChatModelInfo: React.FC = () => {
  const [modelInfo, setModelInfo] = useState<ModelInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [switchingProvider, setSwitchingProvider] = useState(false);
  const [confirmDialogOpen, setConfirmDialogOpen] = useState(false);
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null);
  const [originalProvider, setOriginalProvider] = useState<string | null>(null);
  const userId = useUserId();
  const { token } = useAuth();
  
  // Список доступных провайдеров
  const availableProviders = [
    { value: "openrouter", label: "OpenRouter" },
    { value: "deepseek", label: "DeepSeek" },
    { value: "openai", label: "OpenAI" },
  ];

  const fetchModelInfo = useCallback(async (showRefreshing = false) => {
    if (showRefreshing) {
      setRefreshing(true);
    }
    
    try {
      // Пробуем получить из API с user_id
      try {
        const url = userId ? `/api/model-info?user_id=${encodeURIComponent(userId)}` : "/api/model-info";
        const response = await fetch(url);
        if (response.ok) {
          const data = await response.json();
          console.log("[ChatModelInfo] Данные получены из API:", data);
          // Безопасная обработка данных с проверкой типов
          const model = (data.model && typeof data.model === "string") ? data.model : "unknown";
          const displayName = (data.displayName && typeof data.displayName === "string") 
            ? data.displayName 
            : (data.model_name && typeof data.model_name === "string")
              ? data.model_name
              : (data.model && typeof data.model === "string")
                ? data.model
                : "Неизвестная модель";
          setModelInfo({
            model: model,
            displayName: displayName,
            provider: data.provider || undefined,
          });
          setLoading(false);
          setRefreshing(false);
          return;
        } else {
          console.warn("[ChatModelInfo] API вернул статус:", response.status, response.statusText);
        }
      } catch (e) {
        console.error("Ошибка при запросе информации о модели:", e);
      }

      // Fallback: используем переменные окружения из window (если они доступны)
      // Или просто показываем заглушку
      setModelInfo({
        model: "unknown",
        displayName: "Модель не определена",
        provider: undefined,
      });
      setLoading(false);
      setRefreshing(false);
    } catch (error) {
      console.error("Ошибка при получении информации о модели:", error);
      setModelInfo({
        model: "unknown",
        displayName: "Ошибка загрузки",
        provider: undefined,
      });
      setLoading(false);
      setRefreshing(false);
    }
  }, [userId]);

  useEffect(() => {
    // Первоначальная загрузка
    fetchModelInfo();

    // Подписываемся на событие обновления модели
    const handleModelUpdate = () => {
      console.log("[ChatModelInfo] Получено событие обновления модели");
      fetchModelInfo(true);
    };
    
    window.addEventListener(MODEL_UPDATE_EVENT, handleModelUpdate);

    // Периодическое обновление каждые 30 секунд
    const intervalId = setInterval(() => {
      fetchModelInfo(false);
    }, 30000);

    return () => {
      window.removeEventListener(MODEL_UPDATE_EVENT, handleModelUpdate);
      clearInterval(intervalId);
    };
  }, [fetchModelInfo, userId]);

  // Ручное обновление при клике
  const handleRefresh = () => {
    fetchModelInfo(true);
  };

  // Функция для проверки текущего провайдера
  const checkCurrentProvider = async (): Promise<string | null> => {
    try {
      const headers: HeadersInit = {
        "Content-Type": "application/json",
      };
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
      
      const response = await fetch(`${API_BASE}/tool_server/get_current_provider`, {
        method: "POST",
        headers: headers,
        body: JSON.stringify({
          kwargs: {},
          thread_id: "",
          checkpoint_id: "",
        }),
      });

      if (!response.ok) {
        throw new Error("Не удалось получить информацию о провайдере");
      }

      const result = await response.json();
      const data = typeof result.data === "string" ? result.data : result.data?.data || result.data;

      // Парсим ответ
      if (typeof data === "string") {
        const lines = data.split("\n");
        for (const line of lines) {
          if (line.includes("Текущий провайдер:")) {
            const provider = line.replace("Текущий провайдер:", "").trim().toLowerCase();
            return provider;
          }
        }
      }
      return null;
    } catch (error) {
      console.error("[ChatModelInfo] Ошибка при проверке провайдера:", error);
      return null;
    }
  };

  // Функция для переключения провайдера
  const switchProvider = async (provider: string): Promise<boolean> => {
    try {
      setSwitchingProvider(true);
      
      // Сохраняем исходный провайдер для отката
      const currentProvider = await checkCurrentProvider();
      setOriginalProvider(currentProvider);

      // Вызываем switch_provider через tool_server API
      const headers: HeadersInit = {
        "Content-Type": "application/json",
      };
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
      
      const response = await fetch(`${API_BASE}/tool_server/switch_provider`, {
        method: "POST",
        headers: headers,
        body: JSON.stringify({
          kwargs: {
            provider: provider,
          },
          thread_id: "",
          checkpoint_id: "",
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.message || `HTTP ${response.status}: ${response.statusText}`);
      }

      const result = await response.json();
      const resultData = typeof result.data === "string" ? result.data : result.data?.data || result.data;

      // Проверяем результат переключения
      if (typeof resultData === "string" && resultData.toLowerCase().includes("ошибка")) {
        throw new Error(resultData);
      }

      // Ждем немного, чтобы изменения применились
      await new Promise(resolve => setTimeout(resolve, 1000));

      // Проверяем, что провайдер действительно переключен
      const newProvider = await checkCurrentProvider();
      if (newProvider && newProvider.toLowerCase() === provider.toLowerCase()) {
        toast.success(`Провайдер успешно переключен на ${availableProviders.find(p => p.value === provider)?.label || provider}`);
        // Обновляем информацию о модели
        fetchModelInfo(true);
        triggerModelUpdate();
        return true;
      } else {
        throw new Error(`Провайдер не переключен. Ожидался: ${provider}, получен: ${newProvider || "неизвестно"}`);
      }
    } catch (error) {
      console.error("[ChatModelInfo] Ошибка при переключении провайдера:", error);
      const errorMessage = error instanceof Error ? error.message : "Неизвестная ошибка";
      toast.error(`Ошибка при переключении провайдера: ${errorMessage}`);
      
      // Пытаемся вернуть исходный провайдер
      if (originalProvider && originalProvider !== provider) {
        try {
          const rollbackHeaders: HeadersInit = {
            "Content-Type": "application/json",
          };
          if (token) {
            rollbackHeaders["Authorization"] = `Bearer ${token}`;
          }
          
          await fetch(`${API_BASE}/tool_server/switch_provider`, {
            method: "POST",
            headers: rollbackHeaders,
            body: JSON.stringify({
              kwargs: {
                provider: originalProvider,
              },
              thread_id: "",
              checkpoint_id: "",
            }),
          });
          toast.info(`Попытка вернуть исходный провайдер: ${originalProvider}`);
          fetchModelInfo(true);
        } catch (rollbackError) {
          console.error("[ChatModelInfo] Ошибка при откате провайдера:", rollbackError);
          toast.error("Не удалось вернуть исходный провайдер. Пожалуйста, переключите вручную.");
        }
      }
      
      return false;
    } finally {
      setSwitchingProvider(false);
      setOriginalProvider(null);
    }
  };

  // Обработчик выбора провайдера из выпадающего списка
  const handleProviderSelect = (provider: string) => {
    if (provider === modelInfo?.provider?.toLowerCase()) {
      toast.info("Этот провайдер уже выбран");
      return;
    }
    setSelectedProvider(provider);
    setConfirmDialogOpen(true);
  };

  // Обработчик подтверждения переключения
  const handleConfirmSwitch = async () => {
    if (!selectedProvider) return;
    
    setConfirmDialogOpen(false);
    const success = await switchProvider(selectedProvider);
    setSelectedProvider(null);
  };

  // Обработчик отмены переключения
  const handleCancelSwitch = () => {
    setConfirmDialogOpen(false);
    setSelectedProvider(null);
  };

  if (loading) {
    return null; // Не показываем ничего во время загрузки
  }

  if (!modelInfo) {
    console.warn("[ChatModelInfo] modelInfo отсутствует после загрузки");
    return null;
  }

  // Используем displayName из API, если он есть, иначе форматируем model
  const getDisplayName = (): string => {
    if (modelInfo.displayName && modelInfo.displayName !== "unknown") {
      return modelInfo.displayName;
    }
    
    // Fallback: форматируем model, если displayName не доступен
    const model = modelInfo.model;
    // Проверяем, что model является строкой и не пустой
    if (!model || typeof model !== "string" || model === "unknown") {
      return "Неизвестная модель";
    }

    // Убираем префиксы провайдеров
    // Добавляем проверку на каждом этапе, чтобы избежать ошибок
    let displayName: string = model;
    try {
      // Проверяем, что displayName все еще строка перед каждым replace
      if (typeof displayName !== "string") {
        return model || "Неизвестная модель";
      }
      
      displayName = displayName
        .replace(/^openrouter:/i, "")
        .replace(/^gigachat:/i, "")
        .replace(/^openai:/i, "")
        .replace(/^deepseek:/i, "");

      // Проверяем после первой цепочки replace
      if (typeof displayName !== "string" || !displayName) {
        return model || "Неизвестная модель";
      }

      // Форматируем для лучшей читаемости
      // Например: mistralai/devstral-2512:free -> Mistral Devstral 2 2512 (free)
      displayName = displayName
        .replace(/^mistralai\//i, "Mistral ")
        .replace(/^google\//i, "Google ")
        .replace(/^meta-llama\//i, "Meta ")
        .replace(/^deepseek\//i, "DeepSeek ")
        .replace(/devstral-(\d+)/i, "Devstral $1")
        .replace(/:free$/i, " (free)")
        .replace(/-/g, " ")
        .replace(/\b\w/g, (l) => l.toUpperCase());
      
      // Финальная проверка после всех replace
      if (typeof displayName !== "string" || !displayName) {
        return model || "Неизвестная модель";
      }
    } catch (error) {
      console.error("[ChatModelInfo] Ошибка при форматировании имени модели:", error, "model:", model);
      return model || "Неизвестная модель";
    }

    // Финальная проверка, что displayName не стал undefined или null
    if (!displayName || typeof displayName !== "string") {
      return model || "Неизвестная модель";
    }

    return displayName;
  };

  const displayName = getDisplayName();
  
  console.log("[ChatModelInfo] Рендеринг компонента, displayName:", displayName);

  const getProviderBadgeVariant = (provider?: string) => {
    if (!provider) return "outline";
    switch (provider.toLowerCase()) {
      case "openrouter":
        return "default";
      case "deepseek":
        return "secondary";
      case "openai":
        return "outline";
      default:
        return "outline";
    }
  };

  const getProviderLabel = (provider?: string) => {
    if (!provider) return null;
    switch (provider.toLowerCase()) {
      case "openrouter":
        return "OpenRouter";
      case "deepseek":
        return "DeepSeek";
      case "openai":
        return "OpenAI";
      default:
        return provider;
    }
  };

  const providerLabel = getProviderLabel(modelInfo.provider);

  return (
    <>
      <div 
        className="flex items-center gap-2 px-3 py-1.5 text-xs text-muted-foreground bg-muted/50 rounded-md border border-border/50 transition-colors"
      >
        <Cpu size={14} className="opacity-70" />
        {providerLabel && (
          <>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Badge 
                  variant={getProviderBadgeVariant(modelInfo.provider)} 
                  className="text-xs cursor-pointer hover:opacity-80 transition-opacity flex items-center gap-1"
                  onClick={(e) => e.stopPropagation()}
                  title="Нажмите для переключения провайдера"
                >
                  {providerLabel}
                  <ChevronDown size={12} />
                </Badge>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start">
                {availableProviders.map((provider) => (
                  <DropdownMenuItem
                    key={provider.value}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleProviderSelect(provider.value);
                    }}
                    disabled={switchingProvider || provider.value === modelInfo?.provider?.toLowerCase()}
                  >
                    {provider.label}
                    {provider.value === modelInfo?.provider?.toLowerCase() && " (текущий)"}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
            <span className="opacity-50">/</span>
          </>
        )}
        <span 
          className="font-medium cursor-pointer hover:opacity-80 transition-opacity"
          onClick={handleRefresh}
          title="Нажмите для обновления информации о модели"
        >
          {displayName}
        </span>
        {(refreshing || switchingProvider) && (
          <RefreshCw size={12} className="animate-spin opacity-70" />
        )}
      </div>

      {/* Диалог подтверждения переключения провайдера */}
      <AlertDialog open={confirmDialogOpen} onOpenChange={setConfirmDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Подтверждение переключения провайдера</AlertDialogTitle>
            <AlertDialogDescription>
              Вы уверены, что хотите переключить провайдера с <strong>{providerLabel}</strong> на{" "}
              <strong>{availableProviders.find(p => p.value === selectedProvider)?.label || selectedProvider}</strong>?
              <br />
              <br />
              После переключения будет проведена проверка, что провайдер успешно переключен.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={handleCancelSwitch}>Отмена</AlertDialogCancel>
            <AlertDialogAction 
              onClick={handleConfirmSwitch}
              disabled={switchingProvider}
            >
              {switchingProvider ? "Переключение..." : "Подтвердить"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
};

export default ChatModelInfo;
