import React, { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "./AuthContext";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Trash2, Edit2, Plus, X, Check } from "lucide-react";
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

const API_BASE = "/api";

export const UserTokens: React.FC = () => {
  const { user, token } = useAuth();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  
  const [tinkoffToken, setTinkoffToken] = useState("");
  const [tinkoffAccountId, setTinkoffAccountId] = useState("");
  const [tinkoffSandbox, setTinkoffSandbox] = useState(false);
  const [githubToken, setGithubToken] = useState("");
  const [googleCalendarCredentials, setGoogleCalendarCredentials] = useState("");
  const [googleCalendarId, setGoogleCalendarId] = useState("");

  // Состояния для почтовых ящиков
  const [emailAccounts, setEmailAccounts] = useState<any[]>([]);
  const [loadingAccounts, setLoadingAccounts] = useState(false);
  const [editingAccount, setEditingAccount] = useState<string | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [accountToDelete, setAccountToDelete] = useState<string | null>(null);
  
  // Форма для нового/редактируемого ящика
  const [accountForm, setAccountForm] = useState({
    email: "",
    password: "",
    smtp_host: "",
    smtp_port: "587",
    imap_host: "",
    imap_port: "993",
  });

  useEffect(() => {
    if (!user || !token) {
      navigate("/");
      return;
    }
    loadUserData();
    loadEmailAccounts();
  }, [user, token]);

  const loadUserData = async () => {
    if (!user || !token) return;
    
    setLoading(true);
    try {
      const response = await fetch(`${API_BASE}/auth/me/tokens`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        throw new Error("Не удалось загрузить данные пользователя");
      }

      const tokensData = await response.json();
      
      setTinkoffToken(tokensData.tinkoff_token || "");
      setTinkoffAccountId(tokensData.tinkoff_account_id || "");
      setTinkoffSandbox(tokensData.tinkoff_sandbox || false);
      setGithubToken(tokensData.github_token || "");
      setGoogleCalendarCredentials(tokensData.google_calendar_credentials || "");
      setGoogleCalendarId(tokensData.google_calendar_id || "");
    } catch (error: any) {
      toast.error("Ошибка загрузки данных", {
        description: error.message,
      });
    } finally {
      setLoading(false);
    }
  };

  const loadEmailAccounts = async () => {
    if (!user || !token) return;
    
    setLoadingAccounts(true);
    try {
      const response = await fetch(`${API_BASE}/email-accounts/`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        throw new Error("Не удалось загрузить почтовые ящики");
      }

      const accounts = await response.json();
      setEmailAccounts(accounts);
    } catch (error: any) {
      toast.error("Ошибка загрузки почтовых ящиков", {
        description: error.message,
      });
    } finally {
      setLoadingAccounts(false);
    }
  };

  const handleAddAccount = () => {
    // Используем пустую строку для обозначения нового ящика (не null)
    setEditingAccount("");
    setAccountForm({
      email: "",
      password: "",
      smtp_host: "",
      smtp_port: "587",
      imap_host: "",
      imap_port: "993",
    });
  };

  const handleEditAccount = (account: any) => {
    setEditingAccount(account.id);
    setAccountForm({
      email: account.email,
      password: "", // Не показываем пароль при редактировании
      smtp_host: account.smtp_host,
      smtp_port: account.smtp_port.toString(),
      imap_host: account.imap_host,
      imap_port: account.imap_port.toString(),
    });
  };

  const handleSaveAccount = async () => {
    if (!user || !token) return;

    // Обязательны только email и пароль (при создании)
    if (!accountForm.email || (!editingAccount && !accountForm.password)) {
      toast.error("Заполните email и пароль");
      return;
    }

    try {
      const url = editingAccount && editingAccount !== ""
        ? `${API_BASE}/email-accounts/${editingAccount}/`
        : `${API_BASE}/email-accounts/`;
      
      const method = (editingAccount && editingAccount !== "") ? "PUT" : "POST";
      
      const body: any = {
        email: accountForm.email,
      };
      
      // Пароль обязателен только при создании
      if (accountForm.password) {
        body.password = accountForm.password;
      }
      
      // Хосты и порты опциональны - если не указаны, сервер определит автоматически
      if (accountForm.smtp_host) {
        body.smtp_host = accountForm.smtp_host;
      }
      if (accountForm.smtp_port && accountForm.smtp_port !== "") {
        body.smtp_port = parseInt(accountForm.smtp_port);
      }
      if (accountForm.imap_host) {
        body.imap_host = accountForm.imap_host;
      }
      if (accountForm.imap_port && accountForm.imap_port !== "") {
        body.imap_port = parseInt(accountForm.imap_port);
      }

      const response = await fetch(url, {
        method,
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(body),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Ошибка сохранения");
      }

      toast.success((editingAccount && editingAccount !== "") ? "Ящик обновлен" : "Ящик добавлен");
      setEditingAccount(null);
      setAccountForm({
        email: "",
        password: "",
        smtp_host: "",
        smtp_port: "587",
        imap_host: "",
        imap_port: "993",
      });
      await loadEmailAccounts();
    } catch (error: any) {
      toast.error("Ошибка сохранения", {
        description: error.message,
      });
    }
  };

  const handleDeleteAccount = async () => {
    if (!user || !token || !accountToDelete) return;

    try {
      const response = await fetch(`${API_BASE}/email-accounts/${accountToDelete}/`, {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        throw new Error("Ошибка удаления");
      }

      toast.success("Ящик удален");
      setDeleteDialogOpen(false);
      setAccountToDelete(null);
      await loadEmailAccounts();
    } catch (error: any) {
      toast.error("Ошибка удаления", {
        description: error.message,
      });
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!user || !token) return;

    setSaving(true);
    try {
      const response = await fetch(`${API_BASE}/users/${user.user_id}/`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          tinkoff_token: tinkoffToken || null,
          tinkoff_account_id: tinkoffAccountId || null,
          tinkoff_sandbox: tinkoffSandbox,
          github_token: githubToken || null,
          google_calendar_credentials: googleCalendarCredentials || null,
          google_calendar_id: googleCalendarId || null,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Ошибка сохранения");
      }

      toast.success("Токены успешно сохранены");
    } catch (error: any) {
      toast.error("Ошибка сохранения", {
        description: error.message,
      });
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen w-screen bg-background">
        <div className="text-center">
          <div className="loader"></div>
          <p className="mt-4 text-muted-foreground">Загрузка...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center min-h-screen w-screen bg-background p-4">
      <Card className="w-full max-w-2xl mx-auto">
        <CardHeader>
          <CardTitle>Управление токенами</CardTitle>
          <CardDescription>
            Настройте токены для различных сервисов. Токены будут использоваться при работе с соответствующими агентами.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-6">
            {/* Tinkoff Invest */}
            <div className="space-y-4 border-b pb-6">
              <h3 className="text-lg font-semibold">Tinkoff Invest</h3>
              <div className="space-y-2">
                <Label htmlFor="tinkoff_token">Tinkoff Token</Label>
                <Input
                  id="tinkoff_token"
                  type="password"
                  value={tinkoffToken}
                  onChange={(e) => setTinkoffToken(e.target.value)}
                  placeholder="t.ваш_токен"
                  disabled={saving}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="tinkoff_account_id">Account ID</Label>
                <Input
                  id="tinkoff_account_id"
                  type="text"
                  value={tinkoffAccountId}
                  onChange={(e) => setTinkoffAccountId(e.target.value)}
                  placeholder="12345678"
                  disabled={saving}
                />
              </div>
              <div className="flex items-center space-x-2">
                <Switch
                  id="tinkoff_sandbox"
                  checked={tinkoffSandbox}
                  onCheckedChange={setTinkoffSandbox}
                  disabled={saving}
                />
                <Label htmlFor="tinkoff_sandbox" className="cursor-pointer">
                  Использовать Sandbox режим
                </Label>
              </div>
            </div>

            {/* GitHub */}
            <div className="space-y-4 border-b pb-6">
              <h3 className="text-lg font-semibold">GitHub</h3>
              <div className="space-y-2">
                <Label htmlFor="github_token">GitHub Personal Access Token</Label>
                <Input
                  id="github_token"
                  type="password"
                  value={githubToken}
                  onChange={(e) => setGithubToken(e.target.value)}
                  placeholder="ghp_ваш_токен"
                  disabled={saving}
                />
              </div>
            </div>

            {/* Google Calendar */}
            <div className="space-y-4 border-b pb-6">
              <h3 className="text-lg font-semibold">Google Calendar</h3>
              <div className="space-y-2">
                <Label htmlFor="google_calendar_credentials">
                  Service Account Credentials (JSON строка или путь к файлу)
                </Label>
                <Input
                  id="google_calendar_credentials"
                  type="text"
                  value={googleCalendarCredentials}
                  onChange={(e) => setGoogleCalendarCredentials(e.target.value)}
                  placeholder="/app/credentials/calendar.json или JSON строка"
                  disabled={saving}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="google_calendar_id">Calendar ID</Label>
                <Input
                  id="google_calendar_id"
                  type="text"
                  value={googleCalendarId}
                  onChange={(e) => setGoogleCalendarId(e.target.value)}
                  placeholder="user@example.com или primary"
                  disabled={saving}
                />
              </div>
            </div>

            {/* Почтовые ящики */}
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-semibold">Почтовые ящики</h3>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={handleAddAccount}
                  disabled={saving || (editingAccount !== null && editingAccount !== undefined)}
                >
                  <Plus size={16} className="mr-2" />
                  Добавить ящик
                </Button>
              </div>

              {editingAccount === null && emailAccounts.length === 0 && !loadingAccounts && (
                <p className="text-sm text-muted-foreground">Нет добавленных почтовых ящиков</p>
              )}

              {loadingAccounts && (
                <p className="text-sm text-muted-foreground">Загрузка...</p>
              )}

              {editingAccount === null && emailAccounts.map((account) => (
                <div
                  key={account.id}
                  className="border rounded-lg p-4 space-y-2"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex-1">
                      <p className="font-medium">{account.email}</p>
                      <p className="text-sm text-muted-foreground">
                        SMTP: {account.smtp_host}:{account.smtp_port} | 
                        IMAP: {account.imap_host}:{account.imap_port}
                      </p>
                    </div>
                    <div className="flex gap-2">
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => handleEditAccount(account)}
                        disabled={saving}
                      >
                        <Edit2 size={16} />
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          setAccountToDelete(account.id);
                          setDeleteDialogOpen(true);
                        }}
                        disabled={saving}
                        className="text-destructive hover:text-destructive"
                      >
                        <Trash2 size={16} />
                      </Button>
                    </div>
                  </div>
                </div>
              ))}

              {(editingAccount !== null && editingAccount !== undefined) && (
                <div className="border rounded-lg p-4 space-y-4 bg-muted/50">
                  <div className="flex items-center justify-between">
                    <h4 className="font-medium">
                      {editingAccount ? "Редактирование ящика" : "Новый ящик"}
                    </h4>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setEditingAccount(null);
                        setAccountForm({
                          email: "",
                          password: "",
                          smtp_host: "",
                          smtp_port: "587",
                          imap_host: "",
                          imap_port: "993",
                        });
                      }}
                    >
                      <X size={16} />
                    </Button>
                  </div>
                  
                  <div className="space-y-2">
                    <Label htmlFor="account_email">Email адрес *</Label>
                    <Input
                      id="account_email"
                      type="email"
                      value={accountForm.email}
                      onChange={(e) => setAccountForm({ ...accountForm, email: e.target.value })}
                      placeholder="user@example.com"
                      disabled={saving}
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="account_password">
                      Пароль {editingAccount ? "(оставьте пустым, чтобы не менять)" : "*"}
                    </Label>
                    <Input
                      id="account_password"
                      type="password"
                      value={accountForm.password}
                      onChange={(e) => setAccountForm({ ...accountForm, password: e.target.value })}
                      placeholder="Пароль от почтового ящика"
                      disabled={saving}
                    />
                  </div>

                  <div className="text-sm text-muted-foreground mb-2">
                    Настройки сервера определяются автоматически для основных почтовых провайдеров (Gmail, Yandex, Mail.ru, Hoster.ru и др.). Заполните вручную только если используете нестандартный сервер.
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="account_smtp_host">SMTP сервер (опционально)</Label>
                      <Input
                        id="account_smtp_host"
                        type="text"
                        value={accountForm.smtp_host}
                        onChange={(e) => setAccountForm({ ...accountForm, smtp_host: e.target.value })}
                        placeholder="Автоматически по email"
                        disabled={saving}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="account_smtp_port">SMTP порт (опционально)</Label>
                      <Input
                        id="account_smtp_port"
                        type="number"
                        value={accountForm.smtp_port}
                        onChange={(e) => setAccountForm({ ...accountForm, smtp_port: e.target.value })}
                        placeholder="587"
                        disabled={saving}
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="account_imap_host">IMAP сервер (опционально)</Label>
                      <Input
                        id="account_imap_host"
                        type="text"
                        value={accountForm.imap_host}
                        onChange={(e) => setAccountForm({ ...accountForm, imap_host: e.target.value })}
                        placeholder="Автоматически по email"
                        disabled={saving}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="account_imap_port">IMAP порт (опционально)</Label>
                      <Input
                        id="account_imap_port"
                        type="number"
                        value={accountForm.imap_port}
                        onChange={(e) => setAccountForm({ ...accountForm, imap_port: e.target.value })}
                        placeholder="993"
                        disabled={saving}
                      />
                    </div>
                  </div>

                  <Button
                    type="button"
                    onClick={handleSaveAccount}
                    disabled={saving}
                    className="w-full"
                  >
                    <Check size={16} className="mr-2" />
                    {editingAccount ? "Сохранить изменения" : "Добавить ящик"}
                  </Button>
                </div>
              )}
            </div>

            <div className="flex gap-4 pt-4">
              <Button type="submit" disabled={saving} className="flex-1">
                {saving ? "Сохранение..." : "Сохранить токены"}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => navigate("/")}
                disabled={saving}
              >
                Отмена
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Удалить почтовый ящик?</AlertDialogTitle>
            <AlertDialogDescription>
              Это действие нельзя отменить. Почтовый ящик будет удален безвозвратно.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDeleteAccount}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Удалить
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};

