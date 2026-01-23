import React, { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "../Auth/AuthContext";
import { toast } from "sonner";
import { Trash2, Edit2, Plus, X, Check, Eye, EyeOff } from "lucide-react";
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
import { Textarea } from "@/components/ui/textarea";

const API_BASE = "/api";

interface Secret {
  id: string;
  name: string;
  value: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export const SecretsTab: React.FC = () => {
  const { user, token } = useAuth();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [secrets, setSecrets] = useState<Secret[]>([]);
  const [editingSecret, setEditingSecret] = useState<string | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [secretToDelete, setSecretToDelete] = useState<string | null>(null);
  const [showValues, setShowValues] = useState<Record<string, boolean>>({});

  // Форма для нового/редактируемого секрета
  const [secretForm, setSecretForm] = useState({
    name: "",
    value: "",
    description: "",
  });

  useEffect(() => {
    if (user && token) {
      loadSecrets();
    }
  }, [user, token]);

  const loadSecrets = async () => {
    if (!user || !token) return;

    setLoading(true);
    try {
      const response = await fetch(`${API_BASE}/secrets/`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        throw new Error("Не удалось загрузить секреты");
      }

      const secretsData = await response.json();
      setSecrets(secretsData);
    } catch (error: any) {
      toast.error("Ошибка загрузки секретов", {
        description: error.message,
      });
    } finally {
      setLoading(false);
    }
  };

  const handleAddSecret = () => {
    setEditingSecret("");
    setSecretForm({
      name: "",
      value: "",
      description: "",
    });
  };

  const handleEditSecret = (secret: Secret) => {
    setEditingSecret(secret.id);
    setSecretForm({
      name: secret.name,
      value: secret.value,
      description: secret.description || "",
    });
  };

  const handleSaveSecret = async () => {
    if (!user || !token) return;

    if (!secretForm.name || !secretForm.value) {
      toast.error("Заполните название и значение секрета");
      return;
    }

    try {
      const url =
        editingSecret && editingSecret !== ""
          ? `${API_BASE}/secrets/${editingSecret}/`
          : `${API_BASE}/secrets/`;

      const method = editingSecret && editingSecret !== "" ? "PUT" : "POST";

      const body: any = {
        name: secretForm.name,
        value: secretForm.value,
      };

      if (secretForm.description) {
        body.description = secretForm.description;
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

      toast.success(editingSecret && editingSecret !== "" ? "Секрет обновлен" : "Секрет добавлен");
      setEditingSecret(null);
      setSecretForm({
        name: "",
        value: "",
        description: "",
      });
      await loadSecrets();
    } catch (error: any) {
      toast.error("Ошибка сохранения", {
        description: error.message,
      });
    }
  };

  const handleDeleteSecret = async () => {
    if (!user || !token || !secretToDelete) return;

    try {
      const response = await fetch(`${API_BASE}/secrets/${secretToDelete}/`, {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        throw new Error("Ошибка удаления");
      }

      toast.success("Секрет удален");
      setDeleteDialogOpen(false);
      setSecretToDelete(null);
      await loadSecrets();
    } catch (error: any) {
      toast.error("Ошибка удаления", {
        description: error.message,
      });
    }
  };

  const toggleShowValue = (secretId: string) => {
    setShowValues((prev) => ({
      ...prev,
      [secretId]: !prev[secretId],
    }));
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <div className="loader"></div>
          <p className="mt-4 text-muted-foreground">Загрузка...</p>
        </div>
      </div>
    );
  }

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>Секреты</CardTitle>
          <CardDescription>
            Управляйте секретами (API ключи, токены, пароли и другие конфиденциальные данные).
            Секреты доступны в инструменте python через словарь SECRETS.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold">Секреты</h3>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleAddSecret}
                disabled={saving || (editingSecret !== null && editingSecret !== undefined)}
              >
                <Plus size={16} className="mr-2" />
                Добавить секрет
              </Button>
            </div>

            {editingSecret === null && secrets.length === 0 && !loading && (
              <p className="text-sm text-muted-foreground">Нет добавленных секретов</p>
            )}

            {editingSecret === null &&
              secrets.map((secret) => (
                <div key={secret.id} className="border rounded-lg p-4 space-y-2">
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <p className="font-medium">{secret.name}</p>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => toggleShowValue(secret.id)}
                          className="h-6 w-6 p-0"
                        >
                          {showValues[secret.id] ? (
                            <EyeOff size={14} />
                          ) : (
                            <Eye size={14} />
                          )}
                        </Button>
                      </div>
                      {showValues[secret.id] ? (
                        <p className="text-sm font-mono bg-muted p-2 rounded break-all">
                          {secret.value}
                        </p>
                      ) : (
                        <p className="text-sm text-muted-foreground">••••••••</p>
                      )}
                      {secret.description && (
                        <p className="text-sm text-muted-foreground mt-1">{secret.description}</p>
                      )}
                    </div>
                    <div className="flex gap-2">
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => handleEditSecret(secret)}
                        disabled={saving}
                      >
                        <Edit2 size={16} />
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          setSecretToDelete(secret.id);
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

            {editingSecret !== null && editingSecret !== undefined && (
              <div className="border rounded-lg p-4 space-y-4 bg-muted/50">
                <div className="flex items-center justify-between">
                  <h4 className="font-medium">
                    {editingSecret ? "Редактирование секрета" : "Новый секрет"}
                  </h4>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setEditingSecret(null);
                      setSecretForm({
                        name: "",
                        value: "",
                        description: "",
                      });
                    }}
                  >
                    <X size={16} />
                  </Button>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="secret_name">Название секрета *</Label>
                  <Input
                    id="secret_name"
                    type="text"
                    value={secretForm.name}
                    onChange={(e) => setSecretForm({ ...secretForm, name: e.target.value })}
                    placeholder="например: api_key, github_token"
                    disabled={saving}
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="secret_value">Значение секрета *</Label>
                  <Textarea
                    id="secret_value"
                    value={secretForm.value}
                    onChange={(e) => setSecretForm({ ...secretForm, value: e.target.value })}
                    placeholder="Введите значение секрета"
                    disabled={saving}
                    rows={3}
                    className="font-mono"
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="secret_description">Описание (опционально)</Label>
                  <Textarea
                    id="secret_description"
                    value={secretForm.description}
                    onChange={(e) => setSecretForm({ ...secretForm, description: e.target.value })}
                    placeholder="Описание секрета"
                    disabled={saving}
                    rows={2}
                  />
                </div>

                <Button
                  type="button"
                  onClick={handleSaveSecret}
                  disabled={saving}
                  className="w-full"
                >
                  <Check size={16} className="mr-2" />
                  {editingSecret ? "Сохранить изменения" : "Добавить секрет"}
                </Button>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Удалить секрет?</AlertDialogTitle>
            <AlertDialogDescription>
              Это действие нельзя отменить. Секрет будет удален безвозвратно.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDeleteSecret}
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

