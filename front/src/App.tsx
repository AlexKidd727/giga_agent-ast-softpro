import React, { useRef, useState, useMemo } from "react";
import Chat from "./components/Chat";
import { SettingsProvider } from "./components/Settings.tsx";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import Sidebar from "./components/Sidebar.tsx";
import DemoSettings from "./components/demo/DemoSettings.tsx";
import { DemoItemsProvider, useDemoItems } from "./hooks/DemoItemsProvider.tsx";
import DemoChat from "./components/demo/DemoChat.tsx";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { GraphState } from "./interfaces.ts";
import { Message } from "@langchain/langgraph-sdk";
import { RagProvider } from "@/components/rag/providers/RAG.tsx";
import RAGInterface from "@/components/rag";
import { OAuthCallback } from "@/components/mcp/oauth-callback.tsx";
import { UserInfoProvider } from "@/components/providers/user-info.tsx";
import { Toaster } from "@/components/ui/sonner.tsx";
import { AuthProvider } from "./components/Auth/AuthContext";
import { ProtectedRoute } from "./components/Auth/ProtectedRoute";
import { Register } from "./components/Auth/Register";
import { UserTokens } from "./components/Auth/UserTokens";
import { useAuth } from "./components/Auth/AuthContext";

const InnerApp: React.FC = () => {
  const { demoItemsLoaded } = useDemoItems();
  const { user } = useAuth();
  // Можно использовать булево или просто число-счётчик
  const [reloadKey, setReloadKey] = useState(0);
  const [currentThreadId, setCurrentThreadId] = useState<string | null>(null);
  const currentThreadRef = useRef<UseStream<GraphState> | null>(null);
  
  // Создаем ключ, который включает user_id для пересоздания потока при смене пользователя
  const chatKey = useMemo(
    () => `chat-${reloadKey}-${user?.user_id || 'no-user'}`,
    [reloadKey, user?.user_id]
  );

  // Функция для получения информации о текущем чате
  const getCurrentChatInfo = () => {
    if (!currentThreadRef.current || !currentThreadId) {
      return null;
    }
    const messages = currentThreadRef.current.messages || [];
    if (messages.length === 0) {
      return null;
    }
    // Ищем первое сообщение от пользователя
    const firstHumanMessage = messages.find((msg: Message) => msg.type === "human");
    if (!firstHumanMessage) {
      return null;
    }
    const messageContent =
      typeof firstHumanMessage.content === "string"
        ? firstHumanMessage.content
        : Array.isArray(firstHumanMessage.content)
          ? firstHumanMessage.content
              .map((item: unknown) =>
                typeof item === "string" ? item : (item as { text?: string })?.text || "",
              )
              .join(" ")
          : "";
    return {
      threadId: currentThreadId,
      firstMessage: messageContent,
    };
  };

  // эта функция будет прокидываться в SidebarComponent
  const handleNavigateAndReload = () => {
    // переключаем флаг, чтобы сделать новый key у соседнего компонента
    setReloadKey((prev) => prev + 1);
    if (currentThreadRef.current) {
      currentThreadRef.current.stop();
    }
  };

  const handleThreadIdChange = (threadId: string) => {
    setCurrentThreadId(threadId);
  };

  const handleThreadReady = (thread: UseStream<GraphState>) => {
    currentThreadRef.current = thread;
  };
  // Показываем загрузку, но не блокируем рендеринг
  if (!demoItemsLoaded) {
    return (
      <div className="flex items-center justify-center h-screen w-screen">
        <div className="text-center">
          <div className="loader"></div>
          <p className="mt-4 text-muted-foreground">Загрузка...</p>
        </div>
      </div>
    );
  }
  return (
        <Routes>
          <Route path="/register" element={<Register />} />
          <Route
            path="*"
            element={
              <ProtectedRoute>
                <Sidebar 
                  onNewChat={handleNavigateAndReload}
                  getCurrentChatInfo={getCurrentChatInfo}
                >
                  <Routes>
                    <Route
                      path="/"
                      element={
                        <Chat
                          key={chatKey}
                          onThreadIdChange={handleThreadIdChange}
                          onThreadReady={handleThreadReady}
                        />
                      }
                    />
                    <Route
                      path="/threads/:threadId"
                      element={
                        <Chat
                          key={chatKey}
                          onThreadIdChange={handleThreadIdChange}
                          onThreadReady={handleThreadReady}
                        />
                      }
                    />
                    <Route
                      path="/demo/:demoIndex"
                      element={
                        <DemoChat
                          key={reloadKey}
                          onContinue={handleNavigateAndReload}
                          onThreadIdChange={handleThreadIdChange}
                          onThreadReady={handleThreadReady}
                        />
                      }
                    />
                    <Route path="/oauth/callback" element={<OAuthCallback />} />
                    <Route path="/rag" element={<RAGInterface />} />
                    <Route path="/demo/settings" element={<DemoSettings />} />
                    <Route path="/tokens" element={<UserTokens />} />
                  </Routes>
                </Sidebar>
              </ProtectedRoute>
            }
          />
        </Routes>
  );
};

const App: React.FC = () => {
  return (
    <DemoItemsProvider>
      <Toaster />
      <SettingsProvider>
        <AuthProvider>
          <RagProvider>
            <UserInfoProvider>
              <div className="flex h-auto w-full mx-auto print:h-auto">
                <BrowserRouter>
                  <InnerApp />
                </BrowserRouter>
              </div>
            </UserInfoProvider>
          </RagProvider>
        </AuthProvider>
      </SettingsProvider>
    </DemoItemsProvider>
  );
};

export default App;
