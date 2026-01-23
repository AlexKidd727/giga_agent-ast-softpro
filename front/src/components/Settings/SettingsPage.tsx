import React, { useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../Auth/AuthContext";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { TokensTab, TokensTabRef } from "./TokensTab";
import { EmailTab } from "./EmailTab";
import { PreferencesTab } from "./PreferencesTab";
import { SecretsTab } from "./SecretsTab";
import { ContextTab } from "./ContextTab";
import { ToolsTab } from "./ToolsTab";
import { KnowledgeTab } from "./KnowledgeTab";
import { AdminTab } from "./AdminTab";
import { Key, Mail, Settings as SettingsIcon, X, Download, Upload, Lock, Brain, Cog, Files, Save, Shield } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "sonner";
import { useSettingsData } from "./SettingsDataContext";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";

const API_BASE = "/api";

const SettingsPageContent: React.FC = () => {
  const { user, token } = useAuth();
  const navigate = useNavigate();
  const { isLoading, isSaving, saveSettings } = useSettingsData();
  const [exporting, setExporting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importDialogOpen, setImportDialogOpen] = useState(false);
  const [overwriteExisting, setOverwriteExisting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const tokensTabRef = useRef<TokensTabRef>(null);
  
  // Проверяем, является ли пользователь админом
  const isAdmin = user?.is_admin || false;
  
  // Отладочный вывод для проверки статуса админа
  React.useEffect(() => {
    console.log("🔍 [SettingsPage] Проверка статуса админа:", {
      user: user ? { user_id: user.user_id, username: user.username, is_admin: user.is_admin } : null,
      isAdmin,
    });
  }, [user, isAdmin]);
  
  // Получаем активную вкладку из URL параметров
  const [activeTab, setActiveTab] = useState<string>(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get("tab") || "tokens";
  });

  // Если пользователь не авторизован, перенаправляем на главную
  React.useEffect(() => {
    if (!user || !token) {
      navigate("/");
    }
  }, [user, token, navigate]);

  // Обработчик сохранения всех настроек
  const handleSaveAll = async () => {
    // Сохраняем настройки через контекст
    const success = await saveSettings();
    
    // Сохраняем токены отдельно (они не входят в общие настройки)
    // Токены сохраняются через отдельный API endpoint в TokensTab
    // Пока что просто сохраняем настройки, токены можно сохранить отдельно при необходимости
    
    if (success) {
      toast.success("Все настройки успешно сохранены");
    } else {
      toast.error("Ошибка сохранения настроек");
    }
  };

  // Обновляем URL при изменении вкладки
  React.useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    params.set("tab", activeTab);
    window.history.replaceState({}, "", `${window.location.pathname}?${params.toString()}`);
  }, [activeTab]);

  const handleExport = async () => {
    if (!user || !token) return;

    setExporting(true);
    try {
      const response = await fetch(`${API_BASE}/settings/export`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        throw new Error("Не удалось экспортировать настройки");
      }

      const data = await response.json();
      
      // Создаем JSON файл для скачивания
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `settings_export_${new Date().toISOString().split("T")[0]}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      toast.success("Настройки успешно экспортированы");
    } catch (error: any) {
      toast.error("Ошибка экспорта", {
        description: error.message,
      });
    } finally {
      setExporting(false);
    }
  };

  const handleImportClick = () => {
    setImportDialogOpen(true);
  };

  const handleFileSelect = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file || !user || !token) return;

    setImporting(true);
    try {
      const text = await file.text();
      const importData = JSON.parse(text);

      const response = await fetch(`${API_BASE}/settings/import`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          ...importData,
          overwrite: overwriteExisting,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Ошибка импорта");
      }

      const result = await response.json();
      toast.success("Настройки успешно импортированы", {
        description: `Импортировано элементов: ${result.imported_items}`,
      });

      // Перезагружаем страницу для обновления данных
      window.location.reload();
    } catch (error: any) {
      toast.error("Ошибка импорта", {
        description: error.message,
      });
    } finally {
      setImporting(false);
      setImportDialogOpen(false);
      setOverwriteExisting(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  };

  if (!user || !token) {
    return null;
  }

  return (
    <div className="flex items-start justify-center min-h-screen w-screen bg-background p-4">
      <div className="w-full max-w-6xl mx-auto">
        <Card className="w-full">
          <CardHeader>
            <CardTitle className="text-2xl">Настройки</CardTitle>
            <CardDescription>
              Управляйте токенами, почтовыми ящиками, предпочтениями, секретами, контекстом, инструментами и знаниями
            </CardDescription>
          </CardHeader>
          <CardContent className="p-6">

        <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
          <TabsList className={`grid w-full mb-6 gap-1 ${isAdmin ? 'grid-cols-4 md:grid-cols-8' : 'grid-cols-4 md:grid-cols-7'}`}>
            <TabsTrigger value="tokens" className="flex items-center gap-2">
              <Key size={16} />
              Токены
            </TabsTrigger>
            <TabsTrigger value="email" className="flex items-center gap-2">
              <Mail size={16} />
              Почта
            </TabsTrigger>
            <TabsTrigger value="preferences" className="flex items-center gap-2">
              <SettingsIcon size={16} />
              Предпочтения
            </TabsTrigger>
            <TabsTrigger value="secrets" className="flex items-center gap-2">
              <Lock size={16} />
              Секреты
            </TabsTrigger>
            <TabsTrigger value="context" className="flex items-center gap-2">
              <Brain size={16} />
              Контекст
            </TabsTrigger>
            <TabsTrigger value="tools" className="flex items-center gap-2">
              <Cog size={16} />
              Инструменты
            </TabsTrigger>
            <TabsTrigger value="knowledge" className="flex items-center gap-2">
              <Files size={16} />
              Знания
            </TabsTrigger>
            {isAdmin && (
              <TabsTrigger value="admin" className="flex items-center gap-2">
                <Shield size={16} />
                Админка
              </TabsTrigger>
            )}
          </TabsList>

          <TabsContent value="tokens" className="mt-0">
            <TokensTab ref={tokensTabRef} />
          </TabsContent>

          <TabsContent value="email" className="mt-0">
            <EmailTab />
          </TabsContent>

          <TabsContent value="preferences" className="mt-0">
            <PreferencesTab />
          </TabsContent>

          <TabsContent value="secrets" className="mt-0">
            <SecretsTab />
          </TabsContent>

          <TabsContent value="context" className="mt-0">
            <ContextTab />
          </TabsContent>

          <TabsContent value="tools" className="mt-0">
            <ToolsTab />
          </TabsContent>

          <TabsContent value="knowledge" className="mt-0">
            <KnowledgeTab />
          </TabsContent>

          {isAdmin && (
            <TabsContent value="admin" className="mt-0">
              <AdminTab />
            </TabsContent>
          )}
        </Tabs>

        {/* Общие кнопки управления внизу */}
        <div className="mt-6 pt-6 border-t flex justify-between items-center gap-4">
          <div className="flex gap-2">
            <Button
              variant="outline"
              onClick={handleExport}
              disabled={exporting}
              className="flex items-center gap-2"
            >
              <Download size={16} />
              {exporting ? "Экспорт..." : "Экспорт"}
            </Button>
            <Button
              variant="outline"
              onClick={handleImportClick}
              disabled={importing}
              className="flex items-center gap-2"
            >
              <Upload size={16} />
              {importing ? "Импорт..." : "Импорт"}
            </Button>
          </div>
          <div className="flex gap-2">
            <Button
              onClick={handleSaveAll}
              disabled={isSaving || isLoading}
              className="flex items-center gap-2"
            >
              <Save size={16} />
              {isSaving ? "Сохранение..." : "Сохранить"}
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                // Восстанавливаем путь, который был до открытия настроек
                // Это предотвращает сброс чата при закрытии настроек
                const previousPath = sessionStorage.getItem("previousPathBeforeSettings");
                if (previousPath && previousPath !== "/settings") {
                  sessionStorage.removeItem("previousPathBeforeSettings");
                  navigate(previousPath);
                } else if (window.history.length > 1) {
                  // Fallback: используем навигацию назад, если сохраненного пути нет
                  navigate(-1);
                } else {
                  navigate("/");
                }
              }}
              className="flex items-center gap-2"
            >
              <X size={16} />
              Закрыть
            </Button>
          </div>
        </div>
          </CardContent>
        </Card>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        accept=".json"
        onChange={handleFileSelect}
        style={{ display: "none" }}
      />

      <AlertDialog open={importDialogOpen} onOpenChange={setImportDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Импорт настроек</AlertDialogTitle>
            <AlertDialogDescription>
              Выберите JSON файл с настройками для импорта. Существующие настройки будут обновлены или добавлены новые.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="py-4 space-y-4">
            <div className="flex items-center space-x-2">
              <Switch
                id="overwrite"
                checked={overwriteExisting}
                onCheckedChange={setOverwriteExisting}
              />
              <Label htmlFor="overwrite" className="cursor-pointer">
                Перезаписать существующие настройки
              </Label>
            </div>
            <p className="text-sm text-muted-foreground">
              Если включено, существующие настройки будут перезаписаны. Если выключено, будут добавлены только новые настройки.
            </p>
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                fileInputRef.current?.click();
              }}
            >
              Выбрать файл
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};

export const SettingsPage: React.FC = () => {
  // SettingsDataProvider теперь на уровне приложения (App.tsx)
  return <SettingsPageContent />;
};

