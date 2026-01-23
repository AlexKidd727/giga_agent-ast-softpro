import React, { useEffect, useState } from "react";
import { useAuth } from "./Auth/AuthContext";
import { Badge } from "./ui/badge";
import { Loader2 } from "lucide-react";

const API_BASE = "/api";

interface ProviderInfo {
  provider: string;
  model: string;
  fullString: string;
  apiKeyStatus: Record<string, string>;
}

export const ProviderInfo: React.FC = () => {
  const { token } = useAuth();
  const [providerInfo, setProviderInfo] = useState<ProviderInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadProviderInfo = async () => {
    if (!token) {
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      // Вызываем тул get_current_provider через tool_server API
      // tool_server работает на порту 9091, но доступен через прокси /api/tool_server
      const response = await fetch(`${API_BASE}/tool_server/get_current_provider`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
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

      // Парсим ответ тула
      if (typeof data === "string") {
        const lines = data.split("\n");
        const info: Partial<ProviderInfo> = {
          apiKeyStatus: {},
        };

        for (const line of lines) {
          if (line.startsWith("Текущий провайдер:")) {
            info.provider = line.replace("Текущий провайдер:", "").trim();
          } else if (line.startsWith("Модель:")) {
            info.model = line.replace("Модель:", "").trim();
          } else if (line.startsWith("Полная строка:")) {
            info.fullString = line.replace("Полная строка:", "").trim();
          } else if (line.includes(":")) {
            const [key, value] = line.split(":").map((s) => s.trim());
            if (key && value && (key.includes("API_KEY") || key.includes("KEY"))) {
              info.apiKeyStatus = info.apiKeyStatus || {};
              info.apiKeyStatus[key] = value;
            }
          }
        }

        if (info.provider && info.model) {
          setProviderInfo(info as ProviderInfo);
        } else {
          setError("Не удалось распарсить информацию о провайдере");
        }
      } else {
        setError("Неожиданный формат ответа");
      }
    } catch (err: any) {
      console.error("Ошибка загрузки информации о провайдере:", err);
      setError(err.message || "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadProviderInfo();
    // Обновляем информацию каждые 30 секунд
    const interval = setInterval(() => {
      void loadProviderInfo();
    }, 30000);
    return () => clearInterval(interval);
  }, [token]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="h-3 w-3 animate-spin" />
        <span>Загрузка...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-xs text-muted-foreground">
        <span className="text-destructive">Ошибка: {error}</span>
      </div>
    );
  }

  if (!providerInfo) {
    return null;
  }

  const getProviderBadgeVariant = (provider: string) => {
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

  const getProviderLabel = (provider: string) => {
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

  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="text-muted-foreground">Провайдер:</span>
      <Badge variant={getProviderBadgeVariant(providerInfo.provider)} className="text-xs">
        {getProviderLabel(providerInfo.provider)}
      </Badge>
      {providerInfo.model && (
        <>
          <span className="text-muted-foreground">/</span>
          <span className="text-muted-foreground truncate max-w-[100px]" title={providerInfo.model}>
            {providerInfo.model}
          </span>
        </>
      )}
    </div>
  );
};
