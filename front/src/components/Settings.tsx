import React, { createContext, useContext, useEffect, useState, useCallback, useRef } from "react";
import { Secret } from "@/interfaces.ts";
import { useAuth } from "./Auth/AuthContext";
import { loadUserPreferences, updateUserPreferences } from "@/utils/settingsApi";

type Settings = {
  autoApprove: boolean;
  debugMode: boolean;
  sideBarOpen: boolean;
  contextInstructions: string;
  contextSecrets: Array<Secret>;
  activeCollections: Record<string, boolean>;
};

interface SettingsProps {
  children: any[] | any;
}

const defaultSettings: Settings = {
  autoApprove: false,
  debugMode: true, // По умолчанию включен режим отладки
  sideBarOpen: true,
  contextInstructions: "",
  contextSecrets: [],
  activeCollections: {},
};

const SettingsContext = createContext<{
  settings: Settings;
  setSettings: React.Dispatch<React.SetStateAction<Settings>>;
  isLoading: boolean;
}>({ settings: defaultSettings, setSettings: () => {}, isLoading: true });

export const SettingsProvider = ({ children }: SettingsProps) => {
  const { token, isAuthenticated } = useAuth();
  const [settings, setSettings] = useState<Settings>(defaultSettings);
  const [isLoading, setIsLoading] = useState(true);
  const [isInitialized, setIsInitialized] = useState(false);

  // Refs для отслеживания состояния и предотвращения бесконечных циклов
  const prevSettingsRef = useRef<string>("");
  const isSavingRef = useRef(false);
  const hasLoadedOnceRef = useRef(false);
  const prevTokenRef = useRef<string | null>(null);

  // Загрузка настроек из БД при монтировании или изменении токена
  // ВАЖНО: При смене пользователя (изменении токена) настройки автоматически
  // перезагружаются из БД для нового пользователя. Каждый пользователь видит
  // только свои индивидуальные настройки.

  useEffect(() => {
    // Сбрасываем флаг при смене пользователя
    if (prevTokenRef.current !== token) {
      hasLoadedOnceRef.current = false;
      prevTokenRef.current = token;
    }

    if (!isAuthenticated || !token) {
      // Если пользователь не аутентифицирован, используем дефолтные настройки
      setSettings(defaultSettings);
      prevSettingsRef.current = JSON.stringify(defaultSettings);
      setIsLoading(false);
      setIsInitialized(true);
      hasLoadedOnceRef.current = true;
      return;
    }

    const loadSettings = async () => {
      setIsLoading(true);
      try {
        // Загружаем настройки текущего пользователя из БД
        // API автоматически определяет пользователя по токену и возвращает только его настройки
        const preferences = await loadUserPreferences(token);
        
        let loadedSettings: Settings;
        if (preferences?.settings) {
          // Мержим с дефолтными настройками для обратной совместимости
          loadedSettings = {
            ...defaultSettings,
            ...preferences.settings,
          };
        } else {
          // Если настроек нет в БД, используем дефолтные
          loadedSettings = defaultSettings;
        }
        
        setSettings(loadedSettings);
        // Обновляем prevSettingsRef сразу после загрузки, чтобы не сохранять сразу
        prevSettingsRef.current = JSON.stringify(loadedSettings);
        hasLoadedOnceRef.current = true;
      } catch (error) {
        console.error("Ошибка загрузки настроек из БД:", error);
        // В случае ошибки используем дефолтные настройки
        setSettings(defaultSettings);
        prevSettingsRef.current = JSON.stringify(defaultSettings);
        hasLoadedOnceRef.current = true;
      } finally {
        setIsLoading(false);
        setIsInitialized(true);
      }
    };

    loadSettings();
  }, [token, isAuthenticated]);

  // Сохранение настроек в БД при изменении
  // ВАЖНО: Используем useRef для отслеживания предыдущих значений, чтобы избежать бесконечных циклов

  useEffect(() => {
    // Не сохраняем, если еще не инициализированы или пользователь не аутентифицирован
    if (!isInitialized || !isAuthenticated || !token || isLoading || !hasLoadedOnceRef.current) {
      return;
    }

    // Проверяем, действительно ли настройки изменились (сравниваем JSON строки)
    const settingsJson = JSON.stringify(settings);
    if (prevSettingsRef.current === settingsJson || isSavingRef.current) {
      return;
    }

    // Обновляем предыдущие значения ПЕРЕД сохранением
    prevSettingsRef.current = settingsJson;

    // Используем debounce для избежания частых запросов
    const timeoutId = setTimeout(async () => {
      if (isSavingRef.current) return;
      isSavingRef.current = true;
      try {
        await updateUserPreferences(token, {
          settings: settings,
        });
      } catch (error) {
        console.error("Ошибка сохранения настроек в БД:", error);
      } finally {
        isSavingRef.current = false;
      }
    }, 500); // Задержка 500мс для debounce

    return () => clearTimeout(timeoutId);
  }, [settings, isInitialized, isAuthenticated, token, isLoading]);

  // Обертка для setSettings, которая также сохраняет в БД
  const handleSetSettings = useCallback<React.Dispatch<React.SetStateAction<Settings>>>(
    (newSettings) => {
      setSettings((prev) => {
        const updated = typeof newSettings === "function" ? newSettings(prev) : newSettings;
        return updated;
      });
    },
    [],
  );

  return (
    <SettingsContext.Provider value={{ settings, setSettings: handleSetSettings, isLoading }}>
      {children}
    </SettingsContext.Provider>
  );
};

// Хук для удобного доступа
export const useSettings = () => useContext(SettingsContext);
