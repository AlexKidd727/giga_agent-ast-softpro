import React, { useState, useEffect, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { MessageSquare, Trash2, Edit2, X, Check, Loader2 } from "lucide-react";
import { useChatHistory } from "../hooks/useChatHistory";
import { Button } from "./ui/button";
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

interface ChatHistoryListProps {
  onChatSelect?: () => void;
}

const ChatHistoryList: React.FC<ChatHistoryListProps> = ({ onChatSelect }) => {
  const navigate = useNavigate();
  const { threadId } = useParams<{ threadId?: string }>();
  const { chats, deleteChat, updateChatTitle, loading } = useChatHistory();
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [chatToDelete, setChatToDelete] = useState<string | null>(null);
  const [editingChatId, setEditingChatId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [loadingChatId, setLoadingChatId] = useState<string | null>(null);

  // Отслеживаем изменения в списке чатов для отладки
  useEffect(() => {
    console.log(`📋 ChatHistoryList: список чатов обновлен, всего: ${chats.length}`);
    if (chats.length > 0) {
      console.log(`📋 Первые 3 чата:`, chats.slice(0, 3).map(c => ({ threadId: c.threadId, title: c.title })));
    }
  }, [chats]);

  // Ref для хранения таймеров очистки индикатора загрузки
  const loadingTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Отслеживаем загрузку чата при смене threadId
  useEffect(() => {
    // Очищаем предыдущий таймер, если он есть
    if (loadingTimerRef.current) {
      clearTimeout(loadingTimerRef.current);
      loadingTimerRef.current = null;
    }

    if (threadId) {
      // Устанавливаем индикатор загрузки при выборе чата
      setLoadingChatId(threadId);
      
      // Убираем индикатор через задержку (после загрузки)
      // Используем функцию обновления состояния для безопасности
      loadingTimerRef.current = setTimeout(() => {
        setLoadingChatId((current) => {
          // Сбрасываем только если это тот же чат (на случай быстрой смены)
          if (current === threadId) {
            return null;
          }
          return current;
        });
        loadingTimerRef.current = null;
      }, 800); // 800мс для показа индикатора
    } else {
      // Если threadId нет, сразу убираем индикатор
      setLoadingChatId(null);
    }

    // Очистка при размонтировании или смене threadId
    return () => {
      if (loadingTimerRef.current) {
        clearTimeout(loadingTimerRef.current);
        loadingTimerRef.current = null;
      }
    };
  }, [threadId]);

  const handleChatClick = (clickedThreadId: string) => {
    // Очищаем предыдущий таймер
    if (loadingTimerRef.current) {
      clearTimeout(loadingTimerRef.current);
      loadingTimerRef.current = null;
    }

    // Устанавливаем индикатор загрузки при клике
    setLoadingChatId(clickedThreadId);
    navigate(`/threads/${clickedThreadId}`);
    onChatSelect?.();
    
    // Убираем индикатор через задержку (на случай, если useEffect не сработает)
    loadingTimerRef.current = setTimeout(() => {
      setLoadingChatId((current) => {
        // Сбрасываем только если это тот же чат
        if (current === clickedThreadId) {
          return null;
        }
        return current;
      });
      loadingTimerRef.current = null;
    }, 1000); // 1 секунда максимум
  };

  const handleDeleteClick = (e: React.MouseEvent, threadId: string) => {
    e.stopPropagation();
    setChatToDelete(threadId);
    setDeleteDialogOpen(true);
  };

  const handleDeleteConfirm = () => {
    if (chatToDelete) {
      deleteChat(chatToDelete);
      // Если удаляем текущий чат, переходим на главную
      if (chatToDelete === threadId) {
        navigate("/");
      }
      setDeleteDialogOpen(false);
      setChatToDelete(null);
    }
  };

  const handleEditClick = (e: React.MouseEvent, chat: { threadId: string; title: string }) => {
    e.stopPropagation();
    setEditingChatId(chat.threadId);
    setEditTitle(chat.title);
  };

  const handleEditSave = (e: React.MouseEvent, threadId: string) => {
    e.stopPropagation();
    if (editTitle.trim()) {
      updateChatTitle(threadId, editTitle.trim());
    }
    setEditingChatId(null);
    setEditTitle("");
  };

  const handleEditCancel = (e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingChatId(null);
    setEditTitle("");
  };

  const formatDate = (timestamp: number) => {
    const date = new Date(timestamp);
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    const days = Math.floor(diff / (1000 * 60 * 60 * 24));

    if (days === 0) {
      return "Сегодня";
    } else if (days === 1) {
      return "Вчера";
    } else if (days < 7) {
      return `${days} дн. назад`;
    } else {
      return date.toLocaleDateString("ru-RU", {
        day: "numeric",
        month: "short",
      });
    }
  };

  // Показываем индикатор загрузки, если чаты загружаются
  if (loading) {
    return (
      <div className="border-t border-border pt-4">
        <div className="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide px-2">
          История чатов
        </div>
        <div className="p-2 text-xs text-muted-foreground text-center">
          Загрузка чатов...
        </div>
      </div>
    );
  }

  if (chats.length === 0) {
    return (
      <div className="border-t border-border pt-4">
        <div className="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide px-2">
          История чатов
        </div>
        <div className="p-2 text-xs text-muted-foreground text-center">
          Нет сохраненных чатов
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="border-t border-border pt-4">
        <div className="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide px-2">
          История чатов
        </div>
        <div>
          {chats.map((chat) => {
            const isActive = chat.threadId === threadId;
            const isEditing = editingChatId === chat.threadId;
            const isLoading = loadingChatId === chat.threadId;

            return (
              <div
                key={chat.threadId}
                className={`
                  group relative flex items-center p-2 text-sm rounded-lg cursor-pointer
                  transition-colors
                  ${
                    isActive
                      ? "bg-primary/10 text-primary"
                      : "hover:bg-white/10"
                  }
                  ${isLoading ? "opacity-70" : ""}
                `}
                onClick={() => handleChatClick(chat.threadId)}
              >
                {isLoading ? (
                  <Loader2 size={16} className="mr-2 flex-shrink-0 animate-spin" />
                ) : (
                  <MessageSquare size={16} className="mr-2 flex-shrink-0" />
                )}
                {isEditing ? (
                  <div
                    className="flex-1 flex items-center gap-1"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <Input
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          handleEditSave(e as any, chat.threadId);
                        } else if (e.key === "Escape") {
                          handleEditCancel(e as any);
                        }
                      }}
                      className="h-7 text-xs"
                      autoFocus
                    />
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 w-7 p-0"
                      onClick={(e) => handleEditSave(e, chat.threadId)}
                    >
                      <Check size={14} />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 w-7 p-0"
                      onClick={(e) => handleEditCancel(e)}
                    >
                      <X size={14} />
                    </Button>
                  </div>
                ) : (
                  <>
                    <div className="flex-1 min-w-0">
                      <div className="truncate">{chat.title}</div>
                      <div className="text-xs text-muted-foreground mt-0.5">
                        {formatDate(chat.updatedAt)}
                      </div>
                    </div>
                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-6 w-6 p-0"
                        onClick={(e) => handleEditClick(e, chat)}
                      >
                        <Edit2 size={12} />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-6 w-6 p-0 text-destructive hover:text-destructive"
                        onClick={(e) => handleDeleteClick(e, chat.threadId)}
                      >
                        <Trash2 size={12} />
                      </Button>
                    </div>
                  </>
                )}
              </div>
            );
          })}
        </div>
      </div>

      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Удалить чат?</AlertDialogTitle>
            <AlertDialogDescription>
              Это действие нельзя отменить. Чат будет удален из истории.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDeleteConfirm}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Удалить
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
};

export default ChatHistoryList;

