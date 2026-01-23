import React, { useState, useEffect, useCallback, useMemo } from "react";
import { useAuth } from "./Auth/AuthContext";
import { Play, Pause, CheckCircle, XCircle, Clock, RefreshCw, AlertCircle, Eye, EyeOff, Trash2 } from "lucide-react";
import Spinner from "./Spinner";
import TextMarkdown from "./attachments/TextMarkdown";

interface DeferredTask {
  id: string;
  user_id: string;
  message: string;
  priority: number;
  status: string;
  thread_id: string | null;
  result_data: any;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  task_config: any;
}

// Компонент TaskExecutor удален - обработка задач теперь на сервере

const DeferredTasksRunner: React.FC = () => {
  const { user, isAuthenticated } = useAuth();

  const [tasks, setTasks] = useState<DeferredTask[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedTasks, setExpandedTasks] = useState<Set<string>>(new Set());
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [processingStatus, setProcessingStatus] = useState<any>(null);

  // Проверка, является ли пользователь админом
  const isAdmin = useMemo(() => {
    return user?.username === "alexis";
  }, [user?.username]);


  // Загрузка списка задач
  const loadTasks = useCallback(async (): Promise<DeferredTask[]> => {
    if (!isAuthenticated || !isAdmin) return [];

    try {
      setIsLoading(true);
      const token = localStorage.getItem("auth_token");
      if (!token) return [];

      const response = await fetch("/api/deferred-tasks/", {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        let errorMessage = `Ошибка при загрузке задач (${response.status})`;
        try {
          const errorData = await response.json();
          errorMessage = errorData.detail || errorData.message || errorMessage;
        } catch {
          errorMessage = `Ошибка при загрузке задач: ${response.status} ${response.statusText}`;
        }
        throw new Error(errorMessage);
      }

      const data = await response.json();
      console.log("📋 DeferredTasksRunner: Загружены задачи:", data.length, "шт.");
      data.forEach((task: DeferredTask) => {
        console.log(`  - Задача ${task.id}: status=${task.status}, priority=${task.priority}, message="${task.message.substring(0, 50)}..."`);
      });
      setTasks(data);
      setError(null);
      return data;
    } catch (err) {
      console.error("Ошибка при загрузке задач:", err);
      setError(err instanceof Error ? err.message : "Неизвестная ошибка");
      return [];
    } finally {
      setIsLoading(false);
    }
  }, [isAuthenticated, isAdmin]);

  // Получение статуса обработки задач с сервера
  const loadProcessingStatus = useCallback(async () => {
    if (!isAuthenticated || !isAdmin) return;

    try {
      const token = localStorage.getItem("auth_token");
      if (!token) return;

      const response = await fetch("/api/deferred-tasks/status/", {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        throw new Error("Ошибка при получении статуса");
      }

      const status = await response.json();
      setProcessingStatus(status);
      setIsRunning(status.is_running);
      return status;
    } catch (err) {
      console.error("Ошибка при получении статуса:", err);
    }
  }, [isAuthenticated, isAdmin]);

  // Запуск обработки задач на сервере
  const startProcessing = useCallback(async () => {
    console.log("🚀 [NEW] DeferredTasksRunner: startProcessing вызван");
    if (!isAuthenticated || !isAdmin) {
      console.log("❌ [NEW] DeferredTasksRunner: Не авторизован или не админ");
      return;
    }

    try {
      const token = localStorage.getItem("auth_token");
      if (!token) {
        console.log("❌ [NEW] DeferredTasksRunner: Нет токена");
        return;
      }

      console.log("📡 [NEW] DeferredTasksRunner: Отправляем запрос POST /api/deferred-tasks/start/");
      const response = await fetch("/api/deferred-tasks/start/", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      console.log("📡 [NEW] DeferredTasksRunner: Ответ сервера:", response.status, response.statusText);

      if (!response.ok) {
        const errorData = await response.json();
        console.error("❌ [NEW] DeferredTasksRunner: Ошибка от сервера:", errorData);
        throw new Error(errorData.detail || "Ошибка при запуске обработки");
      }

      const result = await response.json();
      console.log("✅ [NEW] DeferredTasksRunner: Обработка задач запущена на сервере:", result);
      setIsRunning(true);
      await loadProcessingStatus();
    } catch (err) {
      console.error("❌ [NEW] DeferredTasksRunner: Ошибка при запуске обработки:", err);
      setError(err instanceof Error ? err.message : "Неизвестная ошибка");
    }
  }, [isAuthenticated, isAdmin, loadProcessingStatus]);

  // Остановка обработки задач на сервере
  const stopProcessing = useCallback(async () => {
    if (!isAuthenticated || !isAdmin) return;

    try {
      const token = localStorage.getItem("auth_token");
      if (!token) return;

      const response = await fetch("/api/deferred-tasks/stop/", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Ошибка при остановке обработки");
      }

      const result = await response.json();
      console.log("⏸️ Обработка задач остановлена:", result);
      setIsRunning(false);
      await loadProcessingStatus();
    } catch (err) {
      console.error("Ошибка при остановке обработки:", err);
      setError(err instanceof Error ? err.message : "Неизвестная ошибка");
    }
  }, [isAuthenticated, isAdmin, loadProcessingStatus]);

  // Обновление статуса задачи
  const updateTaskStatus = useCallback(
    async (
      taskId: string,
      status: string,
      resultData?: any,
      errorMessage?: string,
      threadId?: string
    ) => {
      if (!isAuthenticated || !isAdmin) return;

      try {
        const token = localStorage.getItem("auth_token");
        if (!token) return;

        const updateData: any = { status };
        if (resultData !== undefined) {
          updateData.result_data = resultData;
        }
        if (errorMessage !== undefined) {
          updateData.error_message = errorMessage;
        }
        if (threadId !== undefined) {
          updateData.thread_id = threadId;
        }

        const response = await fetch(`/api/deferred-tasks/${taskId}/`, {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify(updateData),
        });

        if (!response.ok) {
          let errorMessage = `Ошибка при обновлении задачи (${response.status})`;
          try {
            const errorData = await response.json();
            errorMessage = errorData.detail || errorData.message || errorMessage;
          } catch {
            errorMessage = `Ошибка при обновлении задачи: ${response.status} ${response.statusText}`;
          }
          throw new Error(errorMessage);
        }

        await loadTasks();
      } catch (err) {
        console.error("Ошибка при обновлении задачи:", err);
      }
    },
    [isAuthenticated, isAdmin, loadTasks]
  );

  // Удаление задачи
  const deleteTask = useCallback(
    async (taskId: string) => {
      if (!isAuthenticated || !isAdmin) return;

      if (!confirm("Вы уверены, что хотите удалить эту задачу?")) {
        return;
      }

      try {
        const token = localStorage.getItem("auth_token");
        if (!token) return;

        const response = await fetch(`/api/deferred-tasks/${taskId}/`, {
          method: "DELETE",
          headers: {
            Authorization: `Bearer ${token}`,
          },
        });

        if (!response.ok) {
          let errorMessage = `Ошибка при удалении задачи (${response.status})`;
          try {
            const errorData = await response.json();
            errorMessage = errorData.detail || errorData.message || errorMessage;
          } catch {
            errorMessage = `Ошибка при удалении задачи: ${response.status} ${response.statusText}`;
          }
          throw new Error(errorMessage);
        }

        await loadTasks();
      } catch (err) {
        console.error("Ошибка при удалении задачи:", err);
        setError(err instanceof Error ? err.message : "Неизвестная ошибка");
      }
    },
    [isAuthenticated, isAdmin, loadTasks]
  );

  // Изменение статуса на "отработано" (completed)
  const markAsCompleted = useCallback(
    async (taskId: string) => {
      await updateTaskStatus(taskId, "completed");
    },
    [updateTaskStatus]
  );

  // Обновление статуса обработки и задач
  useEffect(() => {
    if (isAdmin) {
      loadProcessingStatus();
      loadTasks();
      const interval = setInterval(() => {
        loadProcessingStatus();
        loadTasks();
      }, 5000); // Обновляем каждые 5 секунд
      return () => clearInterval(interval);
    }
  }, [isAdmin, loadProcessingStatus, loadTasks]);

  const toggleTaskExpansion = (taskId: string) => {
    setExpandedTasks((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(taskId)) {
        newSet.delete(taskId);
      } else {
        newSet.add(taskId);
      }
      return newSet;
    });
  };

  if (!isAdmin) {
    return (
      <div className="p-4 text-center text-gray-500">
        Доступ разрешен только администратору
      </div>
    );
  }

  const pendingTasks = tasks.filter((t) => t.status === "pending");
  const processingTasks = tasks.filter((t) => t.status === "processing");
  const completedTasks = tasks.filter((t) => t.status === "completed");
  const failedTasks = tasks.filter((t) => t.status === "failed");
  const revisionTasks = tasks.filter((t) => t.status === "revision");

  return (
    <div className="p-4 max-w-6xl mx-auto">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-bold">Запуск отложенных задач</h1>
        <div className="flex items-center gap-2">
          <button
            onClick={async () => {
              console.log("🔘 [NEW] DeferredTasksRunner: Нажата кнопка, isRunning:", isRunning);
              if (!isRunning) {
                console.log("▶️ [NEW] DeferredTasksRunner: Запускаем обработку на сервере");
                await startProcessing();
              } else {
                console.log("⏸️ [NEW] DeferredTasksRunner: Останавливаем обработку на сервере");
                await stopProcessing();
              }
            }}
            disabled={isLoading}
            className="px-4 py-2 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {isRunning ? (
              <>
                <Pause className="w-4 h-4" />
                Пауза
              </>
            ) : (
              <>
                <Play className="w-4 h-4" />
                Запуск
              </>
            )}
          </button>
          <button
            onClick={loadTasks}
            disabled={isLoading}
            className="px-4 py-2 rounded bg-gray-600 text-white hover:bg-gray-700 disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-100 border border-red-400 text-red-700 rounded">
          <AlertCircle className="w-4 h-4 inline mr-2" />
          {error}
          <button
            onClick={() => setError(null)}
            className="ml-2 text-red-800 hover:text-red-900"
          >
            ×
          </button>
        </div>
      )}

      {processingStatus && processingStatus.is_running && (
        <div className="mb-4 p-4 bg-blue-50 border border-blue-200 rounded">
          <div className="flex items-center gap-2">
            <Spinner size="16" />
            <span className="font-semibold">Обработка задач запущена на сервере</span>
          </div>
          {processingStatus.statistics && (
            <div className="mt-2 text-sm text-gray-600">
              Обрабатывается: {processingStatus.statistics.processing} | 
              Ожидает: {processingStatus.statistics.pending} | 
              Завершено: {processingStatus.statistics.completed}
            </div>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4 mb-4">
        <div className="p-4 bg-gray-50 rounded">
          <div className="flex items-center gap-2 mb-2">
            <Clock className="w-5 h-5 text-yellow-600" />
            <span className="font-semibold">Ожидание</span>
            <span className="text-gray-500">({pendingTasks.length})</span>
          </div>
        </div>
        <div className="p-4 bg-blue-50 rounded">
          <div className="flex items-center gap-2 mb-2">
            <Spinner size="16" />
            <span className="font-semibold">Обработка</span>
            <span className="text-gray-500">({processingTasks.length})</span>
          </div>
        </div>
        <div className="p-4 bg-green-50 rounded">
          <div className="flex items-center gap-2 mb-2">
            <CheckCircle className="w-5 h-5 text-green-600" />
            <span className="font-semibold">Завершено</span>
            <span className="text-gray-500">({completedTasks.length})</span>
          </div>
        </div>
        <div className="p-4 bg-red-50 rounded">
          <div className="flex items-center gap-2 mb-2">
            <XCircle className="w-5 h-5 text-red-600" />
            <span className="font-semibold">Ошибки</span>
            <span className="text-gray-500">({failedTasks.length})</span>
          </div>
        </div>
        <div className="p-4 bg-orange-50 rounded">
          <div className="flex items-center gap-2 mb-2">
            <AlertCircle className="w-5 h-5 text-orange-600" />
            <span className="font-semibold">Доработка</span>
            <span className="text-gray-500">({revisionTasks.length})</span>
          </div>
        </div>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-lg font-semibold">Список задач</h2>
          <div className="flex items-center gap-2">
            <label className="text-sm">Фильтр:</label>
            <select
              value={statusFilter || ""}
              onChange={(e) => setStatusFilter(e.target.value || null)}
              className="px-3 py-1 text-sm rounded border border-gray-300 dark:border-gray-600 bg-background"
            >
              <option value="">Все</option>
              <option value="pending">Ожидание</option>
              <option value="processing">Обработка</option>
              <option value="completed">Завершено</option>
              <option value="failed">Ошибки</option>
              <option value="revision">Доработка</option>
            </select>
          </div>
        </div>
        {tasks.length === 0 ? (
          <div className="text-center text-gray-500 py-8">Нет задач</div>
        ) : (
          tasks
            .filter((task) => !statusFilter || task.status === statusFilter)
            .map((task) => {
            const isExpanded = expandedTasks.has(task.id);
            return (
              <div
                key={task.id}
                className={`p-4 border rounded ${
                  task.status === "pending"
                    ? "border-yellow-300 bg-yellow-50"
                    : task.status === "processing"
                    ? "border-blue-300 bg-blue-50"
                    : task.status === "completed"
                    ? "border-green-300 bg-green-50"
                    : task.status === "failed"
                    ? "border-red-300 bg-red-50"
                    : "border-orange-300 bg-orange-50"
                }`}
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="font-semibold mb-1">{task.message}</div>
                    <div className="text-sm text-gray-500">
                      Приоритет: {task.priority} | Создано:{" "}
                      {new Date(task.created_at).toLocaleString()}
                      {task.started_at && (
                        <> | Начато: {new Date(task.started_at).toLocaleString()}</>
                      )}
                      {task.completed_at && (
                        <> | Завершено: {new Date(task.completed_at).toLocaleString()}</>
                      )}
                    </div>
                    {task.error_message && (
                      <div className="text-sm text-red-600 mt-1">
                        Ошибка: {task.error_message}
                      </div>
                    )}
                    {task.result_data && (
                      <div className="mt-2">
                        <button
                          onClick={() => toggleTaskExpansion(task.id)}
                          className="text-sm text-blue-600 hover:text-blue-800 flex items-center gap-1"
                        >
                          {isExpanded ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                          {isExpanded ? "Скрыть" : "Показать"} результаты
                        </button>
                        {isExpanded && (
                          <div className="mt-2 p-4 bg-white rounded border border-gray-200 overflow-auto max-h-96">
                            {(() => {
                              try {
                                // Пытаемся распарсить result_data как JSON
                                const resultData = typeof task.result_data === 'string' 
                                  ? JSON.parse(task.result_data) 
                                  : task.result_data;
                                
                                // Если есть markdown поле, используем его
                                if (resultData.markdown) {
                                  return <TextMarkdown>{resultData.markdown}</TextMarkdown>;
                                }
                                
                                // Если есть last_response, используем его
                                if (resultData.last_response) {
                                  return <TextMarkdown>{resultData.last_response}</TextMarkdown>;
                                }
                                
                                // Если result_data - это строка (старый формат), используем её как markdown
                                if (typeof task.result_data === 'string' && !task.result_data.startsWith('{')) {
                                  return <TextMarkdown>{task.result_data}</TextMarkdown>;
                                }
                                
                                // Fallback: показываем как JSON (для отладки)
                                return (
                                  <div className="text-xs font-mono">
                                    <pre>{JSON.stringify(resultData, null, 2)}</pre>
                                  </div>
                                );
                              } catch (e) {
                                // Если не JSON, пытаемся показать как markdown
                                return <TextMarkdown>{String(task.result_data)}</TextMarkdown>;
                              }
                            })()}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                  <div className="flex items-center gap-2 ml-4">
                    {(task.status === "pending" || task.status === "completed") && (
                      <button
                        onClick={() => updateTaskStatus(task.id, "revision")}
                        className="px-3 py-1 text-sm bg-orange-600 text-white rounded hover:bg-orange-700"
                      >
                        На доработку
                      </button>
                    )}
                    {task.status === "revision" && (
                      <button
                        onClick={() => updateTaskStatus(task.id, "pending")}
                        className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700"
                      >
                        Вернуть в очередь
                      </button>
                    )}
                    {task.status === "failed" && (
                      <button
                        onClick={() => updateTaskStatus(task.id, "pending")}
                        className="px-3 py-1 text-sm bg-green-600 text-white rounded hover:bg-green-700"
                      >
                        Перезапустить
                      </button>
                    )}
                    {task.thread_id && (
                      <a
                        href={`/threads/${task.thread_id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="px-3 py-1 text-sm bg-gray-600 text-white rounded hover:bg-gray-700"
                      >
                        Открыть чат
                      </a>
                    )}
                    {task.status !== "completed" && (
                      <button
                        onClick={() => markAsCompleted(task.id)}
                        className="px-3 py-1 text-sm bg-green-600 text-white rounded hover:bg-green-700 flex items-center gap-1"
                        title="Отметить как отработано"
                      >
                        <CheckCircle className="w-4 h-4" />
                        Отработано
                      </button>
                    )}
                    <button
                      onClick={() => deleteTask(task.id)}
                      className="px-3 py-1 text-sm bg-red-600 text-white rounded hover:bg-red-700 flex items-center gap-1"
                      title="Удалить задачу"
                    >
                      <Trash2 className="w-4 h-4" />
                      Удалить
                    </button>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};

export default DeferredTasksRunner;
