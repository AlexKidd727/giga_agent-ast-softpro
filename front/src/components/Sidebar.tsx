import React from "react";
import { useNavigate } from "react-router-dom";
import {
  ChevronRight,
  Plus,
  Printer,
  Files,
  LogOut,
  Key,
} from "lucide-react";
import LogoImage from "../assets/logo.png";
import LogoWhiteImage from "../assets/logo-white.png";
import { useSettings } from "./Settings.tsx";
import { useEffect, useRef, useState } from "react";
import { ragEnabled } from "@/components/rag/utils.ts";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "./Auth/AuthContext";
import ChatHistoryList from "./ChatHistoryList";
import { useChatHistory } from "../hooks/useChatHistory";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "./ui/alert-dialog";
import { Input } from "./ui/input";
import { Label } from "./ui/label";

interface SidebarProps {
  children: React.ReactNode;
  onNewChat: () => void;
  getCurrentChatInfo?: () => { threadId: string; firstMessage: string } | null;
}

const SidebarComponent = ({ children, onNewChat, getCurrentChatInfo }: SidebarProps) => {
  const navigate = useNavigate();
  const { settings, setSettings } = useSettings();
  const { user, logout } = useAuth();
  const { saveChat } = useChatHistory();
  const [isDark, setIsDark] = useState<boolean>(false);
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [pendingChatInfo, setPendingChatInfo] = useState<{ threadId: string; firstMessage: string } | null>(null);
  const [chatTitle, setChatTitle] = useState<string>("");

  // Функция для очистки тегов из текста
  const cleanMessage = (text: string): string => {
    // Убираем теги <task> и </task>
    let cleaned = text.replace(/<task>/gi, "").replace(/<\/task>/gi, "");
    // Убираем лишние пробелы
    cleaned = cleaned.trim();
    return cleaned;
  };

  const didInitRef = useRef<boolean>(false);

  // Инициализация темы из системных настроек/локального значения (без анимации)
  useEffect(() => {
    const stored =
      typeof window !== "undefined" ? localStorage.getItem("theme") : null;
    const prefersDark =
      typeof window !== "undefined" &&
      window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: dark)").matches;
    const initialDark = stored ? stored === "dark" : prefersDark;
    setIsDark(initialDark);
    if (initialDark) {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
    didInitRef.current = true;
  }, []);

  // Реакция на изменения системной темы
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = (e: MediaQueryListEvent) => {
      setIsDark(e.matches);
    };
    if (media.addEventListener) {
      media.addEventListener("change", onChange);
    } else {
      // @ts-ignore: Safari
      media.addListener(onChange);
    }
    return () => {
      if (media.removeEventListener) {
        media.removeEventListener("change", onChange);
      } else {
        // @ts-ignore: Safari
        media.removeListener(onChange);
      }
    };
  }, []);

  // Применение темы при переключении (с анимацией)
  useEffect(() => {
    if (!didInitRef.current) return;
    const root = document.documentElement;
    root.classList.add("theme-animating");
    const timeout = window.setTimeout(() => {
      root.classList.remove("theme-animating");
    }, 300);
    if (isDark) {
      root.classList.add("dark");
    } else {
      root.classList.remove("dark");
    }
    // Храним выбор только при ручном переключении; в авто-режиме — очищаем
    try {
      localStorage.setItem("theme", isDark ? "dark" : "light");
    } catch {}
    return () => window.clearTimeout(timeout);
  }, [isDark]);

  const toggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    setSettings({ ...settings, ...{ sideBarOpen: !settings.sideBarOpen } });
  };

  const handlePrint = (e: React.MouseEvent) => {
    e.stopPropagation();
    window.print();
  };

  const handleRag = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigate("/rag");
  };

  const handleTokens = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigate("/tokens");
  };

  const handleNewChat = () => {
    // Проверяем, есть ли текущий активный чат с сообщениями
    const currentChatInfo = getCurrentChatInfo?.();
    
    if (currentChatInfo) {
      // Показываем диалог подтверждения сохранения
      setPendingChatInfo(currentChatInfo);
      // Устанавливаем начальное название (очищенное от тегов)
      const cleanedTitle = cleanMessage(currentChatInfo.firstMessage);
      setChatTitle(cleanedTitle.slice(0, 100));
      setSaveDialogOpen(true);
    } else {
      // Если нет активного чата, просто переходим к новому
      navigate("/");
      onNewChat();
    }
  };

  const handleSaveDialogConfirm = () => {
    if (pendingChatInfo) {
      // Сохраняем чат с указанным названием
      saveChat(
        pendingChatInfo.threadId,
        pendingChatInfo.firstMessage,
        chatTitle.trim() || undefined
      );
      // Небольшая задержка для обновления состояния перед переходом
      setTimeout(() => {
        setSaveDialogOpen(false);
        setPendingChatInfo(null);
        setChatTitle("");
        // Переходим к новому чату
        navigate("/");
        onNewChat();
      }, 100);
    } else {
      setSaveDialogOpen(false);
      setPendingChatInfo(null);
      setChatTitle("");
      navigate("/");
      onNewChat();
    }
  };

  const handleSaveDialogCancel = () => {
    setSaveDialogOpen(false);
    setPendingChatInfo(null);
    setChatTitle("");
    // Переходим к новому чату без сохранения
    navigate("/");
    onNewChat();
  };

  const handleLogout = async (e: React.MouseEvent) => {
    e.stopPropagation();
    await logout();
    // После выхода пользователь будет перенаправлен на страницу входа через ProtectedRoute
  };

  return (
    <>
      {/* Диалог подтверждения сохранения чата */}
      <AlertDialog open={saveDialogOpen} onOpenChange={setSaveDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Сохранить текущий чат?</AlertDialogTitle>
            <AlertDialogDescription>
              У вас есть активный чат с сообщениями. Введите название для сохранения в историю.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="py-4">
            <Label htmlFor="chat-title" className="text-sm font-medium">
              Название чата
            </Label>
            <Input
              id="chat-title"
              value={chatTitle}
              onChange={(e) => setChatTitle(e.target.value)}
              placeholder="Введите название чата"
              className="mt-2"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter" && chatTitle.trim()) {
                  handleSaveDialogConfirm();
                } else if (e.key === "Escape") {
                  handleSaveDialogCancel();
                }
              }}
              maxLength={100}
            />
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={handleSaveDialogCancel}>
              Отмена
            </AlertDialogCancel>
            <AlertDialogAction 
              onClick={handleSaveDialogConfirm}
              disabled={!chatTitle.trim()}
            >
              Сохранить
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Overlay (только мобильные) */}
      <div
        onClick={toggle}
        className={[
          settings.sideBarOpen
            ? "opacity-100 pointer-events-auto"
            : "opacity-0 pointer-events-none",
          "fixed top-0 left-0 h-full w-full bg-black/50 z-50 print:hidden max-[900px]:block min-[901px]:hidden transition-opacity duration-300 ease-in-out",
        ].join(" ")}
      />

      {/* Sidebar */}
      <div
        className={[
          "fixed top-0 left-0 h-full w-[250px] p-5 backdrop-blur-2xl rounded-r-lg z-[100] transition-transform duration-300 ease-in-out print:hidden",
          "bg-card border text-card-foreground",
          settings.sideBarOpen ? "translate-x-0" : "-translate-x-[250px]",
          "max-[900px]:rounded-none",
        ].join(" ")}
      >
        <div
          className="h-10 bg-cover transition-[width] duration-300 ease-in-out mb-2 opacity-0"
          style={{
            width: settings.sideBarOpen ? 156 : 40,
            backgroundImage: `url(${isDark ? LogoImage : LogoWhiteImage})`,
          }}
        />

        <div
          className="flex items-center p-2 text-sm rounded-lg cursor-pointer hover:bg-white/10"
          onClick={handleNewChat}
        >
          <Plus size={24} className="mr-2" />
          Новый чат
        </div>

        <div
          className="flex items-center p-2 text-sm rounded-lg cursor-pointer hover:bg-white/10"
          onClick={handlePrint}
        >
          <Printer size={24} className="mr-2" />
          Печать
        </div>

        {ragEnabled() && (
          <div
            className="flex items-center p-2 text-sm rounded-lg cursor-pointer hover:bg-white/10"
            onClick={handleRag}
          >
            <Files size={24} className="mr-2" />
            База знаний
          </div>
        )}

        <div
          className="flex items-center p-2 text-sm rounded-lg cursor-pointer hover:bg-white/10"
          onClick={handleTokens}
        >
          <Key size={24} className="mr-2" />
          Токены
        </div>

        {/* Список сохраненных чатов */}
        <ChatHistoryList
          onChatSelect={() => {
            // Закрываем сайдбар на мобильных устройствах при выборе чата
            if (window.innerWidth <= 900) {
              setSettings({ ...settings, ...{ sideBarOpen: false } });
            }
          }}
        />

        {/* Информация о пользователе */}
        {user && (
          <div className="mt-4 mb-2 p-2 text-xs text-muted-foreground border-t border-border pt-4">
            <div className="font-semibold">{user.username}</div>
            {user.email && <div className="text-xs opacity-75">{user.email}</div>}
          </div>
        )}

        {/* Кнопка выхода */}
        <div
          className="flex items-center p-2 text-sm rounded-lg cursor-pointer hover:bg-destructive/10 text-destructive"
          onClick={handleLogout}
        >
          <LogOut size={24} className="mr-2" />
          Выход
        </div>

        <label className="flex items-center p-2 pl-2.5 cursor-pointer text-sm">
          <Switch
            checked={settings.debugMode ?? true}
            onCheckedChange={(checked) => {
              const newSettings = { ...settings, debugMode: checked };
              // Если отладка выключена, автоматически включаем autoApprove
              if (!checked) {
                newSettings.autoApprove = true;
              }
              setSettings(newSettings);
            }}
          />
          <span className="ml-2">Отладка</span>
        </label>

        <label className="flex items-center p-2 pl-2.5 cursor-pointer text-sm">
          <Switch
            checked={settings.autoApprove ?? false}
            disabled={!settings.debugMode} // Отключаем, если режим отладки выключен
            onCheckedChange={(checked) =>
              setSettings({ ...settings, ...{ autoApprove: checked } })
            }
          />
          <span className="ml-2">Auto Approve</span>
        </label>

        {/* Тумблер темы */}
        <label className="flex items-center p-2 pl-2.5 cursor-pointer text-sm select-none">
          <Switch
            checked={isDark}
            onCheckedChange={(checked) => {
              setIsDark(checked);
            }}
          />
          <span className="ml-2">Тёмная тема</span>
        </label>

        <a
          href="https://ast-softpro.ru"
          target="_blank"
          rel="noopener noreferrer"
          className="mt-4 p-2 text-sm text-primary hover:underline text-center block"
        >
          ast-softpro.ru
        </a>
      </div>

      {/* Opener button */}
      <button
        className="fixed top-5 left-5 z-[200] bg-transparent border-0 cursor-pointer flex items-center text-card-foreground transition-[left] duration-300 ease-in-out print:[&>svg]:hidden"
        onClick={toggle}
      >
        <div
          className="h-10 bg-cover transition-[width] duration-300 ease-in-out"
          style={{
            width: settings.sideBarOpen ? 156 : 40,
            backgroundImage: `url(${isDark ? LogoImage : LogoWhiteImage})`,
          }}
        />
        <ChevronRight
          style={{
            transform: settings.sideBarOpen ? "rotate(180deg)" : "rotate(0)",
            marginLeft: "0.3rem",
          }}
        />
      </button>

      {/* Main content */}
      <div
        className={[
          "flex h-screen w-full mx-auto transition-[margin] duration-300 ease-in-out",
          "max-[900px]:max-h-[calc(100vh-75px)]",
          settings.sideBarOpen ? "min-[900px]:ml-[250px]" : "min-[900px]:ml-0",
          "print:!ml-0",
        ].join(" ")}
      >
        {children}
      </div>
    </>
  );
};

export default SidebarComponent;
