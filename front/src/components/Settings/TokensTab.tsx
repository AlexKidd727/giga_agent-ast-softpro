import React, { useState, useEffect, useImperativeHandle, forwardRef } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "../Auth/AuthContext";
import { toast } from "sonner";

const API_BASE = "/api";

export interface TokensTabRef {
  saveTokens: () => Promise<boolean>;
}

export const TokensTab = forwardRef<TokensTabRef>((_props, ref) => {
  const { user, token } = useAuth();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const [tinkoffToken, setTinkoffToken] = useState("");
  const [tinkoffAccountId, setTinkoffAccountId] = useState("");
  const [tinkoffSandbox, setTinkoffSandbox] = useState(false);
  const [githubToken, setGithubToken] = useState("");
  const [googleCalendarCredentials, setGoogleCalendarCredentials] = useState("");
  const [googleCalendarId, setGoogleCalendarId] = useState("");

  useEffect(() => {
    if (user && token) {
      loadUserData();
    }
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

  const saveTokens = async (): Promise<boolean> => {
    if (!user || !token) return false;

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

      return true;
    } catch (error: any) {
      toast.error("Ошибка сохранения токенов", {
        description: error.message,
      });
      return false;
    } finally {
      setSaving(false);
    }
  };

  useImperativeHandle(ref, () => ({
    saveTokens,
  }));

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
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-lg">Управление токенами</CardTitle>
        <CardDescription className="text-sm">
          Настройте токены для различных сервисов. Токены будут использоваться при работе с соответствующими агентами.
        </CardDescription>
      </CardHeader>
      <CardContent className="p-4">
        <div className="space-y-3">
          {/* Tinkoff Invest */}
          <div className="space-y-2">
            <h3 className="text-base font-semibold">Tinkoff Invest</h3>
            <div className="space-y-1.5">
              <Label htmlFor="tinkoff_token" className="text-sm">Tinkoff Token</Label>
              <Input
                id="tinkoff_token"
                type="password"
                value={tinkoffToken}
                onChange={(e) => setTinkoffToken(e.target.value)}
                placeholder="t.ваш_токен"
                disabled={saving}
                className="h-9"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tinkoff_account_id" className="text-sm">Account ID</Label>
              <Input
                id="tinkoff_account_id"
                type="text"
                value={tinkoffAccountId}
                onChange={(e) => setTinkoffAccountId(e.target.value)}
                placeholder="12345678"
                disabled={saving}
                className="h-9"
              />
            </div>
            <div className="flex items-center space-x-2 pt-1">
              <Switch
                id="tinkoff_sandbox"
                checked={tinkoffSandbox}
                onCheckedChange={setTinkoffSandbox}
                disabled={saving}
              />
              <Label htmlFor="tinkoff_sandbox" className="cursor-pointer text-sm">
                Использовать Sandbox режим
              </Label>
            </div>
          </div>

          {/* GitHub */}
          <div className="space-y-2">
            <h3 className="text-base font-semibold">GitHub</h3>
            <div className="space-y-1.5">
              <Label htmlFor="github_token" className="text-sm">GitHub Personal Access Token</Label>
              <Input
                id="github_token"
                type="password"
                value={githubToken}
                onChange={(e) => setGithubToken(e.target.value)}
                placeholder="ghp_ваш_токен"
                disabled={saving}
                className="h-9"
              />
            </div>
          </div>

          {/* Google Calendar */}
          <div className="space-y-2">
            <h3 className="text-base font-semibold">Google Calendar</h3>
            <div className="space-y-1.5">
              <Label htmlFor="google_calendar_credentials" className="text-sm">
                Service Account Credentials (JSON строка или путь к файлу)
              </Label>
              <Input
                id="google_calendar_credentials"
                type="text"
                value={googleCalendarCredentials}
                onChange={(e) => setGoogleCalendarCredentials(e.target.value)}
                placeholder="/app/credentials/calendar.json или JSON строка"
                disabled={saving}
                className="h-9"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="google_calendar_id" className="text-sm">Calendar ID</Label>
              <Input
                id="google_calendar_id"
                type="text"
                value={googleCalendarId}
                onChange={(e) => setGoogleCalendarId(e.target.value)}
                placeholder="alexis@ts-group.ru или primary"
                disabled={saving}
                className="h-9"
              />
            </div>
          </div>

        </div>
      </CardContent>
    </Card>
  );
});

