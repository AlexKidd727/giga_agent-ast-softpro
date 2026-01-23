/**
 * Контекст для управления данными настроек
 * Обеспечивает единоразовую загрузку и централизованное сохранение всех настроек
 */

import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from "react";
import { useAuth } from "../Auth/AuthContext";
import { loadUserPreferences, saveUserPreferences, UserPreferences } from "@/utils/settingsApi";

interface SettingsDataContextType {
  // Данные настроек
  preferences: UserPreferences | null;
  isLoading: boolean;
  isSaving: boolean;
  
  // Функции для работы с данными
  loadSettings: (forceReload?: boolean) => Promise<void>;
  saveSettings: () => Promise<boolean>;
  
  // Функции для обновления данных (для использования в вкладках)
  updateSettings: (updates: Partial<UserPreferences>) => void;
  getSettings: () => UserPreferences | null;
}

const SettingsDataContext = createContext<SettingsDataContextType | null>(null);

export const SettingsDataProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user, token } = useAuth();
  const [preferences, setPreferences] = useState<UserPreferences | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const hasLoadedRef = useRef(false);

  // Загрузка настроек (один раз при монтировании, или принудительно при создании нового чата)
  const loadSettings = useCallback(async (forceReload: boolean = false) => {
    console.log("[PREFERENCES] SettingsDataContext: loadSettings вызван, user=", user?.user_id, ", token exists=", !!token, ", hasLoaded=", hasLoadedRef.current, ", forceReload=", forceReload);
    if (!user || !token) {
      console.log("[PREFERENCES] SettingsDataContext: пропуск загрузки (нет user или token)");
      return;
    }

    // Если уже загружено и не принудительная перезагрузка, пропускаем
    if (hasLoadedRef.current && !forceReload) {
      console.log("[PREFERENCES] SettingsDataContext: пропуск загрузки (уже загружено)");
      return;
    }

    setIsLoading(true);
    try {
      console.log("[PREFERENCES] SettingsDataContext: начало загрузки предпочтений (forceReload=", forceReload, ")");
      const data = await loadUserPreferences(token);
      console.log("[PREFERENCES] SettingsDataContext: предпочтения загружены, data=", data, ", basePreferences=", data?.basePreferences);
      setPreferences(data || {});
      hasLoadedRef.current = true;
    } catch (error) {
      console.error("[PREFERENCES] SettingsDataContext: ошибка загрузки настроек:", error);
      setPreferences({});
    } finally {
      setIsLoading(false);
    }
  }, [user, token]);

  // Загрузка при монтировании
  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  // Обновление настроек (для использования в вкладках)
  const updateSettings = useCallback((updates: Partial<UserPreferences>) => {
    setPreferences((prev) => {
      if (!prev) {
        return updates as UserPreferences;
      }
      return {
        ...prev,
        ...updates,
        settings: {
          ...prev.settings,
          ...updates.settings,
        },
        mcpServers: updates.mcpServers !== undefined ? updates.mcpServers : prev.mcpServers,
        mcpServerTools: {
          ...prev.mcpServerTools,
          ...updates.mcpServerTools,
        },
        basePreferences: updates.basePreferences !== undefined 
          ? updates.basePreferences 
          : prev.basePreferences,
      };
    });
  }, []);

  // Сохранение всех настроек
  const saveSettings = useCallback(async (): Promise<boolean> => {
    if (!user || !token || !preferences) {
      return false;
    }

    setIsSaving(true);
    try {
      const success = await saveUserPreferences(token, preferences);
      if (success) {
        return true;
      }
      return false;
    } catch (error) {
      console.error("Ошибка сохранения настроек:", error);
      return false;
    } finally {
      setIsSaving(false);
    }
  }, [user, token, preferences]);

  const getSettings = useCallback(() => preferences, [preferences]);

  return (
    <SettingsDataContext.Provider
      value={{
        preferences,
        isLoading,
        isSaving,
        loadSettings,
        saveSettings,
        updateSettings,
        getSettings,
      }}
    >
      {children}
    </SettingsDataContext.Provider>
  );
};

export const useSettingsData = () => {
  const context = useContext(SettingsDataContext);
  if (!context) {
    throw new Error("useSettingsData must be used within SettingsDataProvider");
  }
  return context;
};

