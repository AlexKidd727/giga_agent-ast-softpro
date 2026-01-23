import React, { useState, useEffect } from "react";
import { Textarea } from "@/components/ui/textarea";
import { useSettingsData } from "./SettingsDataContext";


export const ContextTab: React.FC = () => {
  const { preferences, isLoading, updateSettings } = useSettingsData();
  const [instructions, setInstructions] = useState<string>("");

  // Загружаем данные из контекста при первом рендере или изменении preferences
  const isInitializedRef = React.useRef(false);
  useEffect(() => {
    if (preferences && !isInitializedRef.current) {
      if (preferences.settings) {
        setInstructions(preferences.settings.contextInstructions || "");
      } else {
        setInstructions("");
      }
      isInitializedRef.current = true;
    }
  }, [preferences]);

  // Обновляем контекст при изменении данных (только после инициализации)
  useEffect(() => {
    if (!isInitializedRef.current) return;
    
    updateSettings({
      settings: {
        ...preferences?.settings,
        contextInstructions: instructions,
      },
    });
  }, [instructions, updateSettings, preferences]);




  if (isLoading) {
    return (
      <div className="space-y-6 p-4">
        <div>
          <h3 className="text-lg font-semibold mb-2">Контекст</h3>
          <p className="text-sm text-muted-foreground">
            Загрузка настроек...
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold mb-2">Контекст</h3>
        <p className="text-sm text-muted-foreground">
          Настройте поведение агента под себя
        </p>
      </div>

      <div className="space-y-6">
        <section className="space-y-2">
          <h3 className="font-medium text-sm">Доп. инструкции</h3>
          <p className="text-sm text-muted-foreground">
            Укажите дополнительные инструкции по поведению агента
          </p>
          <Textarea
            placeholder="Опишите предпочитаемый стиль, ограничения, тон и т.п."
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            className="min-h-28 max-h-67"
          />
        </section>

      </div>

    </div>
  );
};
