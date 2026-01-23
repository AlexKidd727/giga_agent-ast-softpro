import React, { useState, useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useSettingsData } from "./SettingsDataContext";
import { Plus, Trash2, RefreshCw, Eraser } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../Auth/AuthContext";
import { useUserId } from "../../hooks/useUserConfig";

interface PreferencePair {
  key: string;
  value: string;
}

export const PreferencesTab: React.FC = () => {
  const { preferences, isLoading, updateSettings, loadSettings } = useSettingsData();
  const { token } = useAuth();
  const userId = useUserId();
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isClearingCache, setIsClearingCache] = useState(false);
  const [preferencePairs, setPreferencePairs] = useState<PreferencePair[]>([]);
  const lastPreferencesRef = useRef<string>("");

  // Загружаем данные из контекста
  useEffect(() => {
    console.log("[PREFERENCES] PreferencesTab: useEffect triggered, preferences=", preferences);
    
    if (!preferences) {
      console.log("[PREFERENCES] PreferencesTab: preferences отсутствуют, пропуск");
      return;
    }

    // Создаем строку для сравнения, чтобы определить, изменились ли предпочтения
    const currentPrefsString = JSON.stringify(preferences.basePreferences || {});
    
    // Если предпочтения не изменились, пропускаем обновление
    if (currentPrefsString === lastPreferencesRef.current) {
      console.log("[PREFERENCES] PreferencesTab: предпочтения не изменились, пропуск обновления");
      return;
    }

    console.log("[PREFERENCES] PreferencesTab: загрузка предпочтений, basePreferences exists=", !!preferences.basePreferences, ", type=", typeof preferences.basePreferences);
    
    // Загружаем базовые предпочтения из поля basePreferences
    if (preferences.basePreferences && typeof preferences.basePreferences === 'object') {
      const pairs: PreferencePair[] = Object.entries(preferences.basePreferences).map(([key, value]) => ({
        key: key,
        value: String(value || ''),
      }));
      console.log("[PREFERENCES] PreferencesTab: предпочтения загружены, количество пар=", pairs.length, ", пары=", pairs);
      setPreferencePairs(pairs);
      lastPreferencesRef.current = currentPrefsString;
    } else {
      console.log("[PREFERENCES] PreferencesTab: basePreferences отсутствует или не объект, устанавливаем пустой массив");
      setPreferencePairs([]);
      lastPreferencesRef.current = "{}";
    }
  }, [preferences]);

  // Обновляем контекст при изменении данных (только если пользователь редактировал вручную)
  // Используем флаг, чтобы не создавать бесконечный цикл обновлений
  const isUserEditingRef = useRef(false);
  const lastPairsRef = useRef<string>("");

  useEffect(() => {
    // Сравниваем текущие пары с предыдущими, чтобы определить, изменились ли они пользователем
    const currentPairsString = JSON.stringify(preferencePairs);
    
    // Если пары не изменились, пропускаем обновление
    if (currentPairsString === lastPairsRef.current) {
      return;
    }

    // Если это не инициализация (когда lastPairsRef пуст), значит пользователь редактировал
    if (lastPairsRef.current !== "") {
      isUserEditingRef.current = true;
    }

    lastPairsRef.current = currentPairsString;

    // Обновляем контекст только если пользователь редактировал вручную
    if (isUserEditingRef.current) {
      const validPairs = preferencePairs.filter((p) => p.key.trim());
      const preferencesObj: Record<string, string> = {};
      validPairs.forEach((pair) => {
        preferencesObj[pair.key.trim()] = pair.value.trim();
      });

      console.log("[PREFERENCES] PreferencesTab: обновление контекста (пользователь редактировал), preferencesObj=", preferencesObj);
      
      // Обновляем контекст - предпочтения сохраняются в поле basePreferences
      updateSettings({
        basePreferences: preferencesObj,
      });
      
      // Сбрасываем флаг после обновления
      isUserEditingRef.current = false;
    }
  }, [preferencePairs, updateSettings]);

  const handleAddPair = () => {
    setPreferencePairs([...preferencePairs, { key: "", value: "" }]);
  };

  const handleRemovePair = (index: number) => {
    setPreferencePairs(preferencePairs.filter((_, i) => i !== index));
  };

  const handleUpdatePair = (index: number, field: "key" | "value", value: string) => {
    const updated = [...preferencePairs];
    updated[index] = { ...updated[index], [field]: value };
    setPreferencePairs(updated);
  };

  const handleRefresh = async () => {
    setIsRefreshing(true);
    try {
      await loadSettings(true); // Принудительная перезагрузка
      console.log("[PREFERENCES] PreferencesTab: данные обновлены после принудительной перезагрузки");
    } catch (error) {
      console.error("[PREFERENCES] PreferencesTab: ошибка при обновлении данных:", error);
    } finally {
      setIsRefreshing(false);
    }
  };

  // Очистка кэша OpenRouter
  const handleClearOpenRouterCache = async () => {
    setIsClearingCache(true);
    try {
      const url = userId 
        ? `/api/openrouter/clear-cache?user_id=${encodeURIComponent(userId)}`
        : "/api/openrouter/clear-cache";
      
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }

      const response = await fetch(url, {
        method: "POST",
        headers,
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || "Ошибка очистки кэша");
      }

      const result = await response.json();
      console.log("[PREFERENCES] Кэш OpenRouter очищен:", result);
      
      toast.success("Кэш OpenRouter очищен", {
        description: `Очищено элементов: ${result.cleared_items?.length || 0}. Модель сброшена на значение по умолчанию.`,
      });

      // Обновляем отображение модели в шапке чата
      window.dispatchEvent(new CustomEvent("model-update"));
    } catch (error: any) {
      console.error("[PREFERENCES] Ошибка очистки кэша OpenRouter:", error);
      toast.error("Ошибка очистки кэша", {
        description: error.message,
      });
    } finally {
      setIsClearingCache(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <div className="loader"></div>
          <p className="mt-4 text-muted-foreground">Загрузка...</p>
        </div>
      </div>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>Базовые предпочтения</CardTitle>
            <CardDescription>
              Укажите ваши базовые предпочтения в виде пар "ключ-значение". Эти данные будут использоваться агентом, если в запросе не хватает информации.
            </CardDescription>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleRefresh}
            disabled={isRefreshing || isLoading}
            className="flex items-center gap-2"
            title="Обновить данные с сервера"
          >
            <RefreshCw size={16} className={isRefreshing ? "animate-spin" : ""} />
            Обновить
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {preferencePairs.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <p>Нет добавленных предпочтений</p>
              <p className="text-sm mt-2">Нажмите "Добавить предпочтение" для начала</p>
            </div>
          ) : (
            <div className="space-y-3">
              {preferencePairs.map((pair, index) => (
                <div
                  key={index}
                  className="flex gap-2 items-start p-3 border rounded-lg bg-muted/30"
                >
                  <div className="flex-1 grid grid-cols-2 gap-2">
                    <div className="space-y-1">
                      <Label htmlFor={`pref-key-${index}`} className="text-xs">
                        Ключ
                      </Label>
                      <Input
                        id={`pref-key-${index}`}
                        value={pair.key}
                        onChange={(e) => handleUpdatePair(index, "key", e.target.value)}
                        placeholder="например: имя"
                        disabled={isLoading}
                        className="font-medium"
                      />
                    </div>
                    <div className="space-y-1">
                      <Label htmlFor={`pref-value-${index}`} className="text-xs">
                        Значение
                      </Label>
                      <Input
                        id={`pref-value-${index}`}
                        value={pair.value}
                        onChange={(e) => handleUpdatePair(index, "value", e.target.value)}
                        placeholder="например: Иван"
                        disabled={isLoading}
                      />
                    </div>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => handleRemovePair(index)}
                        disabled={isLoading}
                    className="mt-6 text-destructive hover:text-destructive"
                  >
                    <Trash2 size={16} />
                  </Button>
                </div>
              ))}
            </div>
          )}

          <div className="flex gap-2 pt-2">
            <Button
              type="button"
              variant="outline"
              onClick={handleAddPair}
              disabled={isLoading}
              className="flex items-center gap-2"
            >
              <Plus size={16} />
              Добавить предпочтение
            </Button>
          </div>

        </div>
      </CardContent>

      {/* Секция управления OpenRouter */}
      <CardHeader className="border-t mt-4 pt-6">
        <CardTitle className="text-lg">OpenRouter</CardTitle>
        <CardDescription>
          Управление кэшем и настройками модели OpenRouter
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          <div className="flex items-center justify-between p-4 border rounded-lg bg-muted/30">
            <div>
              <p className="font-medium">Очистить кэш модели</p>
              <p className="text-sm text-muted-foreground">
                Сбрасывает выбранную модель OpenRouter на значение по умолчанию из настроек сервера
              </p>
            </div>
            <Button
              type="button"
              variant="outline"
              onClick={handleClearOpenRouterCache}
              disabled={isClearingCache || isLoading}
              className="flex items-center gap-2"
            >
              <Eraser size={16} className={isClearingCache ? "animate-pulse" : ""} />
              {isClearingCache ? "Очистка..." : "Очистить кэш"}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};

