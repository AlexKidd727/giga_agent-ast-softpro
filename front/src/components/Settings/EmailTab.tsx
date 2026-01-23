import React, { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "../Auth/AuthContext";
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

export const EmailTab: React.FC = () => {
  const { user, token } = useAuth();
  const [loadingAccounts, setLoadingAccounts] = useState(false);
  const [saving, setSaving] = useState(false);
  const [emailAccounts, setEmailAccounts] = useState<any[]>([]);
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
    if (user && token) {
      loadEmailAccounts();
    }
  }, [user, token]);

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
      password: "",
      smtp_host: account.smtp_host,
      smtp_port: account.smtp_port.toString(),
      imap_host: account.imap_host,
      imap_port: account.imap_port.toString(),
    });
  };

  const handleSaveAccount = async () => {
    if (!user || !token) return;

    if (!accountForm.email || (!editingAccount && !accountForm.password)) {
      toast.error("Заполните email и пароль");
      return;
    }

    try {
      const url =
        editingAccount && editingAccount !== ""
          ? `${API_BASE}/email-accounts/${editingAccount}/`
          : `${API_BASE}/email-accounts/`;

      const method = editingAccount && editingAccount !== "" ? "PUT" : "POST";

      const body: any = {
        email: accountForm.email,
      };

      if (accountForm.password) {
        body.password = accountForm.password;
      }

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

      toast.success(editingAccount && editingAccount !== "" ? "Ящик обновлен" : "Ящик добавлен");
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

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>Почтовые ящики</CardTitle>
          <CardDescription>
            Управляйте почтовыми ящиками для работы с email агентом.
          </CardDescription>
        </CardHeader>
        <CardContent>
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

            {loadingAccounts && <p className="text-sm text-muted-foreground">Загрузка...</p>}

            {editingAccount === null &&
              emailAccounts.map((account) => (
                <div key={account.id} className="border rounded-lg p-4 space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="flex-1">
                      <p className="font-medium">{account.email}</p>
                      <p className="text-sm text-muted-foreground">
                        SMTP: {account.smtp_host}:{account.smtp_port} | IMAP: {account.imap_host}
                        :{account.imap_port}
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

            {editingAccount !== null && editingAccount !== undefined && (
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
                  Настройки сервера определяются автоматически для основных почтовых провайдеров
                  (Gmail, Yandex, Mail.ru, Hoster.ru и др.). Заполните вручную только если
                  используете нестандартный сервер.
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="account_smtp_host">SMTP сервер (опционально)</Label>
                    <Input
                      id="account_smtp_host"
                      type="text"
                      value={accountForm.smtp_host}
                      onChange={(e) =>
                        setAccountForm({ ...accountForm, smtp_host: e.target.value })
                      }
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
                      onChange={(e) =>
                        setAccountForm({ ...accountForm, smtp_port: e.target.value })
                      }
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
                      onChange={(e) =>
                        setAccountForm({ ...accountForm, imap_host: e.target.value })
                      }
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
                      onChange={(e) =>
                        setAccountForm({ ...accountForm, imap_port: e.target.value })
                      }
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
    </>
  );
};

