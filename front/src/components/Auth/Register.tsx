import React, { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useNavigate } from "react-router-dom";
import { useAuth } from "./AuthContext";

const API_BASE = "/api";

export const Register: React.FC = () => {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    // Валидация
    if (password !== confirmPassword) {
      setError("Пароли не совпадают");
      return;
    }

    if (password.length < 3) {
      setError("Пароль должен содержать минимум 3 символа");
      return;
    }

    if (!username.trim()) {
      setError("Имя пользователя обязательно");
      return;
    }

    setLoading(true);

    try {
      const response = await fetch(`${API_BASE}/users/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          username: username.trim(),
          email: email.trim() || null,
          password: password,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Ошибка регистрации");
      }

      // После успешной регистрации автоматически выполняем вход
      try {
        await login(username.trim(), password);
        // После успешного входа перенаправляем на главную страницу
        navigate("/");
      } catch (loginError: any) {
        // Если автоматический вход не удался, перенаправляем на страницу входа
        setError(loginError.message || "Регистрация успешна, но не удалось выполнить автоматический вход. Пожалуйста, войдите вручную.");
        navigate("/?registered=true");
      }
    } catch (err: any) {
      setError(err.message || "Ошибка регистрации. Попробуйте еще раз.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex items-center justify-center min-h-screen w-screen bg-background">
      <Card className="w-full max-w-md mx-auto">
        <CardHeader>
          <CardTitle>Регистрация</CardTitle>
          <CardDescription>
            Создайте новый аккаунт для доступа к чату
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="username">Имя пользователя *</Label>
              <Input
                id="username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                autoFocus
                disabled={loading}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="email">Email (необязательно)</Label>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={loading}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Пароль *</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                disabled={loading}
                minLength={3}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="confirmPassword">Подтвердите пароль *</Label>
              <Input
                id="confirmPassword"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                disabled={loading}
                minLength={3}
              />
            </div>
            {error && (
              <div className="text-sm text-destructive bg-destructive/10 p-3 rounded-md">
                {error}
              </div>
            )}
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "Регистрация..." : "Зарегистрироваться"}
            </Button>
            <div className="text-center text-sm text-muted-foreground">
              Уже есть аккаунт?{" "}
              <a href="/" className="text-primary hover:underline">
                Войти
              </a>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
};

