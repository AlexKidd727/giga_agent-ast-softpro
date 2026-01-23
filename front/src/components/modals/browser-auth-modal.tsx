import React, { useState, useEffect, useRef } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Loader2, ExternalLink } from "lucide-react";
import axios from "axios";

interface BrowserAuthModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: (cookies: string, sessionId: string) => void;
  siteUrl: string;
  sessionId?: string;
}

/**
 * Модальное окно для ручной авторизации на сайте
 * Открывает сайт в iframe, позволяет пользователю авторизоваться,
 * затем извлекает куки и передает их в browser-service
 */
const BrowserAuthModal: React.FC<BrowserAuthModalProps> = ({
  isOpen,
  onClose,
  onSuccess,
  siteUrl,
  sessionId = "default",
}) => {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string>("");
  const [step, setStep] = useState<"auth" | "processing">("auth");
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [cookiesExtracted, setCookiesExtracted] = useState(false);

  // Сбрасываем состояние при открытии модалки
  useEffect(() => {
    if (isOpen) {
      setStep("auth");
      setError("");
      setCookiesExtracted(false);
      setIsLoading(false);
    }
  }, [isOpen]);

  /**
   * Открывает сайт в browser-service и извлекает куки после авторизации
   */
  const extractCookies = async () => {
    setIsLoading(true);
    setError("");
    setStep("processing");

    try {
      // Сначала открываем сайт в browser-service через WebSocket
      // Это создаст контекст браузера для сессии
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${protocol}//${window.location.host}/browser/ws?task=${encodeURIComponent(`Открой страницу ${siteUrl}`)}&session_id=${sessionId}`;
      const ws = new WebSocket(wsUrl);
      
      await new Promise((resolve, reject) => {
        let resolved = false;
        const timeout = setTimeout(() => {
          if (!resolved) {
            resolved = true;
            ws.close();
            resolve(null); // Таймаут - продолжаем
          }
        }, 10000); // 10 секунд на открытие страницы
        
        ws.onopen = () => {
          // Соединение установлено, ждем ответа от сервера
        };
        
        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            // Если получили сообщение "done", значит задача выполнена
            if (data.type === "done" || data.type === "action") {
              if (!resolved) {
                resolved = true;
                clearTimeout(timeout);
                ws.close();
                resolve(null);
              }
            }
          } catch (e) {
            // Игнорируем ошибки парсинга
          }
        };
        
        ws.onerror = (err) => {
          if (!resolved) {
            resolved = true;
            clearTimeout(timeout);
            ws.close();
            reject(err);
          }
        };
      });

      // Теперь извлекаем куки из открытого браузера
      const response = await axios.post("/api/browser/cookies/extract", {
        siteUrl,
        sessionId,
      });

      if (response.data.success && response.data.cookies) {
        setCookiesExtracted(true);
        
        // Куки уже сохранены в browser-service через extract endpoint
        // Не нужно их передавать повторно через set
        
        if (onSuccess) {
          // Передаем куки как строку JSON для совместимости
          onSuccess(JSON.stringify(response.data.cookies), sessionId);
        }
        
        // Закрываем модалку через небольшую задержку
        setTimeout(() => {
          onClose();
        }, 1000);
      } else {
        setError(response.data.message || "Не удалось получить куки");
        setStep("auth");
      }
    } catch (err: any) {
      console.error("Ошибка при извлечении куков:", err);
      setError(
        err.response?.data?.message ||
          err.message ||
          "Ошибка при получении куков"
      );
      setStep("auth");
    } finally {
      setIsLoading(false);
    }
  };

  // Функция удалена - куки уже сохраняются через extract endpoint

  const handleOpenInNewTab = () => {
    window.open(siteUrl, "_blank");
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="w-full max-w-4xl h-[80vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>Авторизация на сайте</DialogTitle>
          <DialogDescription>
            Авторизуйтесь на сайте, затем нажмите "Получить куки"
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 flex flex-col gap-4 min-h-0">
          {step === "auth" && (
            <>
              <div className="flex items-center justify-between p-2 bg-muted rounded">
                <span className="text-sm font-medium">{siteUrl}</span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleOpenInNewTab}
                  className="gap-2"
                >
                  <ExternalLink size={16} />
                  Открыть в новой вкладке
                </Button>
              </div>

              <div className="flex-1 border rounded-lg overflow-hidden bg-background">
                <iframe
                  ref={iframeRef}
                  src={siteUrl}
                  className="w-full h-full border-0"
                  title="Авторизация"
                  sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox"
                />
              </div>

              <div className="flex items-center justify-between gap-2">
                <div className="text-sm text-muted-foreground">
                  После авторизации нажмите кнопку ниже для получения куков
                </div>
                <div className="flex gap-2">
                  <Button variant="outline" onClick={onClose}>
                    Отмена
                  </Button>
                  <Button onClick={extractCookies} disabled={isLoading}>
                    {isLoading ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        Обработка...
                      </>
                    ) : (
                      "Получить куки"
                    )}
                  </Button>
                </div>
              </div>
            </>
          )}

          {step === "processing" && (
            <div className="flex-1 flex items-center justify-center flex-col gap-4">
              {isLoading ? (
                <>
                  <Loader2 className="h-8 w-8 animate-spin text-primary" />
                  <p className="text-sm text-muted-foreground">
                    Получение куков...
                  </p>
                </>
              ) : cookiesExtracted ? (
                <>
                  <div className="text-green-600 text-lg font-medium">
                    ✓ Куки успешно получены и переданы в browser-service
                  </div>
                  <p className="text-sm text-muted-foreground">
                    Модальное окно закроется автоматически
                  </p>
                </>
              ) : (
                <>
                  <div className="text-destructive text-lg font-medium">
                    Ошибка при получении куков
                  </div>
                  {error && (
                    <p className="text-sm text-muted-foreground">{error}</p>
                  )}
                  <Button onClick={() => setStep("auth")}>
                    Попробовать снова
                  </Button>
                </>
              )}
            </div>
          )}

          {error && step === "auth" && (
            <div className="text-sm text-destructive bg-destructive/10 p-3 rounded">
              {error}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default BrowserAuthModal;

