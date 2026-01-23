import React, { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { useAuth } from "../Auth/AuthContext";
import { toast } from "sonner";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Shield, ShieldCheck, ShieldOff, Server, CheckCircle, XCircle, AlertCircle } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";

const API_BASE = "/api";

interface User {
  id: string;
  username: string;
  email: string | null;
  created_at: string;
  updated_at: string;
  is_admin: boolean;
  has_tinkoff_token: boolean;
  has_github_token: boolean;
  has_google_calendar: boolean;
}

interface MCPServer {
  name: string;
  url: string;
  transport: string;
  status: string;
  tools_count: number;
  tools: Array<{
    name: string;
    description: string;
  }>;
  error?: string;
}

interface MCPRegistryServer {
  name: string;
  url: string;
  transport: string;
  enabled: boolean;
  headers?: Record<string, string>;
  created_at?: string | null;
  updated_at?: string | null;
}

export const AdminTab: React.FC = () => {
  const { user, token } = useAuth();
  const [loading, setLoading] = useState(false);
  const [users, setUsers] = useState<User[]>([]);
  const [updating, setUpdating] = useState<string | null>(null);
  const [mcpServers, setMcpServers] = useState<MCPServer[]>([]);
  const [loadingMcp, setLoadingMcp] = useState(false);
  const [expandedServers, setExpandedServers] = useState<Set<string>>(new Set());

  // MCP registry (источник истины: таблица mcp_server)
  const [mcpRegistry, setMcpRegistry] = useState<MCPRegistryServer[]>([]);
  const [loadingMcpRegistry, setLoadingMcpRegistry] = useState(false);
  const [registrySaving, setRegistrySaving] = useState(false);
  const [registryReloading, setRegistryReloading] = useState(false);

  // Форма добавления/редактирования
  const [editName, setEditName] = useState<string>("");
  const [editUrl, setEditUrl] = useState<string>("");
  const [editTransport, setEditTransport] = useState<string>("http");
  const [editEnabled, setEditEnabled] = useState<boolean>(true);
  const [editAuthHeader, setEditAuthHeader] = useState<string>(""); // значение Authorization

  // Проверяем, является ли текущий пользователь админом
  const isAdmin = user?.is_admin || false;

  useEffect(() => {
    if (isAdmin && token) {
      loadUsers();
      loadMcpServers();
      loadMcpRegistry();
    }
  }, [isAdmin, token]);

  const loadUsers = async () => {
    if (!token) return;

    setLoading(true);
    try {
      const response = await fetch(`${API_BASE}/users/`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        if (response.status === 403) {
          toast.error("Доступ запрещен. Требуются права администратора");
          return;
        }
        throw new Error("Не удалось загрузить список пользователей");
      }

      const usersData = await response.json();
      setUsers(usersData);
    } catch (error) {
      console.error("Ошибка загрузки пользователей:", error);
      toast.error("Ошибка загрузки списка пользователей");
    } finally {
      setLoading(false);
    }
  };

  const loadMcpServers = async () => {
    if (!token) return;

    setLoadingMcp(true);
    try {
      const response = await fetch(`${API_BASE}/admin/mcp-servers/`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        if (response.status === 403) {
          toast.error("Доступ запрещен. Требуются права администратора");
          return;
        }
        throw new Error("Не удалось загрузить информацию о MCP серверах");
      }

      const serversData = await response.json();
      setMcpServers(serversData);
    } catch (error) {
      console.error("Ошибка загрузки MCP серверов:", error);
      toast.error("Ошибка загрузки информации о MCP серверах");
    } finally {
      setLoadingMcp(false);
    }
  };

  const loadMcpRegistry = async () => {
    if (!token) return;
    setLoadingMcpRegistry(true);
    try {
      const response = await fetch(`${API_BASE}/admin/mcp-servers/registry/`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        if (response.status === 403) {
          toast.error("Доступ запрещен. Требуются права администратора");
          return;
        }
        throw new Error("Не удалось загрузить реестр MCP серверов");
      }

      const data = await response.json();
      setMcpRegistry(Array.isArray(data) ? data : []);
    } catch (error) {
      console.error("Ошибка загрузки реестра MCP серверов:", error);
      toast.error("Ошибка загрузки реестра MCP серверов");
    } finally {
      setLoadingMcpRegistry(false);
    }
  };

  const resetRegistryForm = () => {
    setEditName("");
    setEditUrl("");
    setEditTransport("http");
    setEditEnabled(true);
    setEditAuthHeader("");
  };

  const startEditRegistry = (s: MCPRegistryServer) => {
    setEditName(s.name);
    setEditUrl(s.url);
    setEditTransport(s.transport || "http");
    setEditEnabled(!!s.enabled);
    // headers в API маскируются (Authorization=***), поэтому не подставляем автоматически
    setEditAuthHeader("");
  };

  const saveRegistryServer = async () => {
    if (!token) return;
    const name = editName.trim();
    const url = editUrl.trim();
    const transport = (editTransport || "http").trim();
    if (!name) {
      toast.error("Введите имя MCP сервера");
      return;
    }
    if (!url) {
      toast.error("Введите URL MCP сервера");
      return;
    }
    if (transport !== "http" && transport !== "sse") {
      toast.error("transport должен быть http или sse");
      return;
    }

    setRegistrySaving(true);
    try {
      const headers: Record<string, string> = {};
      if (editAuthHeader.trim()) {
        headers.Authorization = editAuthHeader.trim();
      }

      const response = await fetch(`${API_BASE}/admin/mcp-servers/registry/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          name,
          url,
          transport,
          enabled: editEnabled,
          headers,
        }),
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err?.detail || "Не удалось сохранить MCP сервер");
      }

      toast.success("MCP сервер сохранён");
      resetRegistryForm();
      await loadMcpRegistry();
    } catch (error) {
      console.error("Ошибка сохранения MCP сервера:", error);
      toast.error("Ошибка сохранения MCP сервера");
    } finally {
      setRegistrySaving(false);
    }
  };

  const setRegistryEnabled = async (name: string, enabled: boolean) => {
    if (!token) return;
    try {
      const response = await fetch(`${API_BASE}/admin/mcp-servers/registry/${encodeURIComponent(name)}/enabled/`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ enabled }),
      });
      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err?.detail || "Не удалось обновить статус сервера");
      }
      await loadMcpRegistry();
    } catch (error) {
      console.error("Ошибка обновления enabled:", error);
      toast.error("Ошибка обновления статуса MCP сервера");
    }
  };

  const deleteRegistryServer = async (name: string) => {
    if (!token) return;
    if (!confirm(`Удалить MCP сервер '${name}' из реестра?`)) return;
    try {
      const response = await fetch(`${API_BASE}/admin/mcp-servers/registry/${encodeURIComponent(name)}/`, {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });
      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err?.detail || "Не удалось удалить MCP сервер");
      }
      toast.success("MCP сервер удалён");
      await loadMcpRegistry();
    } catch (error) {
      console.error("Ошибка удаления MCP сервера:", error);
      toast.error("Ошибка удаления MCP сервера");
    }
  };

  const reloadMcp = async () => {
    if (!token) return;
    setRegistryReloading(true);
    try {
      const response = await fetch(`${API_BASE}/admin/mcp-servers/reload/`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });
      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err?.detail || "Не удалось выполнить reload MCP");
      }
      toast.success("Reload MCP выполнен");
      await loadMcpServers();
    } catch (error) {
      console.error("Ошибка reload MCP:", error);
      toast.error("Ошибка reload MCP");
    } finally {
      setRegistryReloading(false);
    }
  };

  const toggleServerExpanded = (serverName: string) => {
    const newExpanded = new Set(expandedServers);
    if (newExpanded.has(serverName)) {
      newExpanded.delete(serverName);
    } else {
      newExpanded.add(serverName);
    }
    setExpandedServers(newExpanded);
  };

  const toggleAdminStatus = async (userId: string, currentStatus: boolean) => {
    if (!token) return;

    setUpdating(userId);
    try {
      const response = await fetch(`${API_BASE}/users/${userId}/`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          is_admin: !currentStatus,
        }),
      });

      if (!response.ok) {
        if (response.status === 403) {
          toast.error("Только администраторы могут изменять статус администратора");
          return;
        }
        throw new Error("Не удалось изменить статус администратора");
      }

      const updatedUser = await response.json();
      
      // Обновляем список пользователей
      setUsers(users.map(u => u.id === userId ? updatedUser : u));
      
      toast.success(
        `Пользователь ${updatedUser.username} ${updatedUser.is_admin ? "назначен" : "снят с"} администратором`
      );
    } catch (error) {
      console.error("Ошибка изменения статуса администратора:", error);
      toast.error("Ошибка изменения статуса администратора");
    } finally {
      setUpdating(null);
    }
  };

  if (!isAdmin) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Админка</CardTitle>
          <CardDescription>Управление пользователями</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground">Доступ запрещен. Требуются права администратора.</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Shield className="h-5 w-5" />
          Админка
        </CardTitle>
        <CardDescription>Управление пользователями и MCP серверами</CardDescription>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="users" className="w-full">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="users">Пользователи</TabsTrigger>
            <TabsTrigger value="mcp">MCP Серверы</TabsTrigger>
          </TabsList>
          
          <TabsContent value="users" className="space-y-4">
          {loading ? (
            <p className="text-muted-foreground">Загрузка пользователей...</p>
          ) : users.length === 0 ? (
            <p className="text-muted-foreground">Пользователи не найдены</p>
          ) : (
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <p className="text-sm text-muted-foreground">
                  Всего пользователей: {users.length}
                </p>
                <Button onClick={loadUsers} variant="outline" size="sm">
                  Обновить
                </Button>
              </div>
              
              <div className="border rounded-lg">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Пользователь</TableHead>
                      <TableHead>Email</TableHead>
                      <TableHead>Статус</TableHead>
                      <TableHead>Токены</TableHead>
                      <TableHead>Дата создания</TableHead>
                      <TableHead className="text-right">Действия</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {users.map((userItem) => (
                      <TableRow key={userItem.id}>
                        <TableCell className="font-medium">
                          {userItem.username}
                          {userItem.id === user?.user_id && (
                            <Badge variant="secondary" className="ml-2">Вы</Badge>
                          )}
                        </TableCell>
                        <TableCell>{userItem.email || "-"}</TableCell>
                        <TableCell>
                          {userItem.is_admin ? (
                            <Badge variant="default" className="flex items-center gap-1 w-fit">
                              <ShieldCheck className="h-3 w-3" />
                              Админ
                            </Badge>
                          ) : (
                            <Badge variant="outline" className="flex items-center gap-1 w-fit">
                              <ShieldOff className="h-3 w-3" />
                              Пользователь
                            </Badge>
                          )}
                        </TableCell>
                        <TableCell>
                          <div className="flex gap-1">
                            {userItem.has_tinkoff_token && (
                              <Badge variant="outline" className="text-xs">Tinkoff</Badge>
                            )}
                            {userItem.has_github_token && (
                              <Badge variant="outline" className="text-xs">GitHub</Badge>
                            )}
                            {userItem.has_google_calendar && (
                              <Badge variant="outline" className="text-xs">Calendar</Badge>
                            )}
                            {!userItem.has_tinkoff_token && 
                             !userItem.has_github_token && 
                             !userItem.has_google_calendar && (
                              <span className="text-muted-foreground text-xs">Нет токенов</span>
                            )}
                          </div>
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {new Date(userItem.created_at).toLocaleDateString("ru-RU")}
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-2">
                            <Label htmlFor={`admin-${userItem.id}`} className="text-sm">
                              Админ
                            </Label>
                            <Switch
                              id={`admin-${userItem.id}`}
                              checked={userItem.is_admin}
                              onCheckedChange={() => toggleAdminStatus(userItem.id, userItem.is_admin)}
                              disabled={updating === userItem.id || userItem.id === user?.user_id}
                            />
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>
          )}
          </TabsContent>
          
          <TabsContent value="mcp" className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Реестр MCP серверов</CardTitle>
                <CardDescription>
                  Источник истины — таблица <code>mcp_server</code> в БД. После изменений нажмите Reload, чтобы tool_server перечитал конфиг без рестарта.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-sm text-muted-foreground">
                    Серверов в реестре: {mcpRegistry.length}
                  </div>
                  <div className="flex gap-2">
                    <Button onClick={loadMcpRegistry} variant="outline" size="sm" disabled={loadingMcpRegistry}>
                      Обновить реестр
                    </Button>
                    <Button onClick={reloadMcp} variant="default" size="sm" disabled={registryReloading}>
                      {registryReloading ? "Reload..." : "Reload MCP"}
                    </Button>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div className="space-y-2">
                    <Label>Имя</Label>
                    <Input value={editName} onChange={(e) => setEditName(e.target.value)} placeholder="например: github" />
                  </div>
                  <div className="space-y-2">
                    <Label>URL</Label>
                    <Input value={editUrl} onChange={(e) => setEditUrl(e.target.value)} placeholder="https://host/mcp" />
                  </div>
                  <div className="space-y-2">
                    <Label>Transport (http|sse)</Label>
                    <Input value={editTransport} onChange={(e) => setEditTransport(e.target.value)} placeholder="http" />
                  </div>
                  <div className="space-y-2">
                    <Label>Enabled</Label>
                    <div className="flex items-center gap-2">
                      <Switch checked={editEnabled} onCheckedChange={(v) => setEditEnabled(!!v)} />
                      <span className="text-sm text-muted-foreground">{editEnabled ? "Включён" : "Выключен"}</span>
                    </div>
                  </div>
                  <div className="space-y-2 md:col-span-2">
                    <Label>Authorization header (опционально)</Label>
                    <Input
                      value={editAuthHeader}
                      onChange={(e) => setEditAuthHeader(e.target.value)}
                      placeholder="Bearer XXX или другой формат"
                    />
                    <div className="text-xs text-muted-foreground">
                      Примечание: в списке реестра токены маскируются. Сейчас значение заголовка сохраняется в БД как есть (это можно усилить шифрованием позже).
                    </div>
                  </div>
                </div>

                <div className="flex gap-2">
                  <Button onClick={saveRegistryServer} disabled={registrySaving}>
                    {registrySaving ? "Сохранение..." : "Сохранить"}
                  </Button>
                  <Button variant="outline" onClick={resetRegistryForm}>
                    Сбросить
                  </Button>
                </div>

                <div className="border rounded-lg">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Имя</TableHead>
                        <TableHead>URL</TableHead>
                        <TableHead>Transport</TableHead>
                        <TableHead>Enabled</TableHead>
                        <TableHead className="text-right">Действия</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {loadingMcpRegistry ? (
                        <TableRow>
                          <TableCell colSpan={5} className="text-muted-foreground">
                            Загрузка реестра...
                          </TableCell>
                        </TableRow>
                      ) : mcpRegistry.length === 0 ? (
                        <TableRow>
                          <TableCell colSpan={5} className="text-muted-foreground">
                            Реестр пуст
                          </TableCell>
                        </TableRow>
                      ) : (
                        mcpRegistry.map((s) => (
                          <TableRow key={s.name}>
                            <TableCell className="font-medium">{s.name}</TableCell>
                            <TableCell className="text-xs break-all">{s.url}</TableCell>
                            <TableCell>
                              <Badge variant="outline">{s.transport}</Badge>
                            </TableCell>
                            <TableCell>
                              <Switch checked={!!s.enabled} onCheckedChange={(v) => setRegistryEnabled(s.name, !!v)} />
                            </TableCell>
                            <TableCell className="text-right">
                              <div className="flex justify-end gap-2">
                                <Button variant="outline" size="sm" onClick={() => startEditRegistry(s)}>
                                  Редактировать
                                </Button>
                                <Button variant="destructive" size="sm" onClick={() => deleteRegistryServer(s.name)}>
                                  Удалить
                                </Button>
                              </div>
                            </TableCell>
                          </TableRow>
                        ))
                      )}
                    </TableBody>
                  </Table>
                </div>
              </CardContent>
            </Card>

            {loadingMcp ? (
              <p className="text-muted-foreground">Загрузка информации о MCP серверах...</p>
            ) : mcpServers.length === 0 ? (
              <p className="text-muted-foreground">MCP серверы не настроены</p>
            ) : (
              <div className="space-y-4">
                <div className="flex justify-between items-center">
                  <p className="text-sm text-muted-foreground">
                    Всего MCP серверов: {mcpServers.length}
                  </p>
                  <Button onClick={loadMcpServers} variant="outline" size="sm">
                    Обновить
                  </Button>
                </div>
                
                <div className="space-y-3">
                  {mcpServers.map((server) => (
                    <Card key={server.name}>
                      <CardHeader className="pb-3">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <Server className="h-4 w-4" />
                            <CardTitle className="text-lg">{server.name}</CardTitle>
                            {server.status === "connected" ? (
                              <Badge variant="default" className="flex items-center gap-1">
                                <CheckCircle className="h-3 w-3" />
                                Подключен
                              </Badge>
                            ) : server.status === "failed" ? (
                              <Badge variant="destructive" className="flex items-center gap-1">
                                <XCircle className="h-3 w-3" />
                                Ошибка
                              </Badge>
                            ) : (
                              <Badge variant="outline" className="flex items-center gap-1">
                                <AlertCircle className="h-3 w-3" />
                                Неизвестно
                              </Badge>
                            )}
                          </div>
                        </div>
                        <CardDescription className="mt-2">
                          <div className="space-y-1">
                            <p className="text-xs">URL: {server.url}</p>
                            <p className="text-xs">Транспорт: {server.transport}</p>
                            <p className="text-xs">Инструментов: {server.tools_count}</p>
                          </div>
                        </CardDescription>
                      </CardHeader>
                      {server.tools_count > 0 && (
                        <CardContent>
                          <Collapsible
                            open={expandedServers.has(server.name)}
                            onOpenChange={() => toggleServerExpanded(server.name)}
                          >
                            <CollapsibleTrigger asChild>
                              <Button variant="ghost" size="sm" className="w-full">
                                {expandedServers.has(server.name) ? "Скрыть" : "Показать"} инструменты ({server.tools_count})
                              </Button>
                            </CollapsibleTrigger>
                            <CollapsibleContent className="mt-2">
                              <div className="space-y-2">
                                {server.tools.map((tool, index) => (
                                  <div key={index} className="p-2 border rounded text-sm">
                                    <p className="font-medium">{tool.name}</p>
                                    {tool.description && (
                                      <p className="text-muted-foreground text-xs mt-1">
                                        {tool.description}
                                      </p>
                                    )}
                                  </div>
                                ))}
                              </div>
                            </CollapsibleContent>
                          </Collapsible>
                        </CardContent>
                      )}
                      {server.error && (
                        <CardContent>
                          <p className="text-sm text-destructive">Ошибка: {server.error}</p>
                        </CardContent>
                      )}
                    </Card>
                  ))}
                </div>
              </div>
            )}
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
};

