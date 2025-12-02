import React, { createContext, useContext, useState, useEffect, ReactNode } from "react";

interface User {
  user_id: string;
  username: string;
  email?: string;
}

interface AuthContextType {
  user: User | null;
  token: string | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const API_BASE = "/api";

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Загружаем сохраненную сессию при монтировании
  useEffect(() => {
    const savedToken = localStorage.getItem("auth_token");
    const savedUser = localStorage.getItem("auth_user");

    if (savedToken && savedUser) {
      setToken(savedToken);
      try {
        const parsedUser = JSON.parse(savedUser);
        setUser(parsedUser);
        // Проверяем, что токен еще действителен
        verifyToken(savedToken);
        
        // ВАЖНО: Создаем сеанс в Redis при загрузке пользователя из localStorage
        // Это гарантирует, что сеанс существует даже после перезагрузки страницы
        (async () => {
          try {
            const { createRedisSession } = await import("../../utils/redisApi");
            const redisResult = await createRedisSession(savedToken);
            console.log(`✅ Redis сеанс восстановлен при загрузке: ${redisResult.message}`);
            console.log(`   user_id: ${parsedUser.user_id}`);
          } catch (error) {
            console.error("⚠️ Не удалось восстановить сеанс в Redis при загрузке:", error);
            // Не прерываем процесс загрузки, если Redis недоступен
          }
        })();
      } catch (e) {
        // Если не удалось распарсить, очищаем
        localStorage.removeItem("auth_token");
        localStorage.removeItem("auth_user");
        setLoading(false);
      }
    } else {
      setLoading(false);
    }
  }, []);

  const verifyToken = async (tokenToVerify: string) => {
    try {
      const response = await fetch(`${API_BASE}/auth/me`, {
        headers: {
          Authorization: `Bearer ${tokenToVerify}`,
        },
      });

      if (response.ok) {
        const userData = await response.json();
        setUser(userData);
        setToken(tokenToVerify);
      } else {
        // Токен недействителен
        localStorage.removeItem("auth_token");
        localStorage.removeItem("auth_user");
        setToken(null);
        setUser(null);
      }
    } catch (error) {
      console.error("Ошибка проверки токена:", error);
      localStorage.removeItem("auth_token");
      localStorage.removeItem("auth_user");
      setToken(null);
      setUser(null);
    } finally {
      setLoading(false);
    }
  };

  const login = async (username: string, password: string) => {
    const response = await fetch(`${API_BASE}/auth/login`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ username, password }),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "Ошибка входа");
    }

    const data = await response.json();
    
    // Проверяем, не меняется ли пользователь
    const currentUserId = user?.user_id;
    const newUserId = data.user_id;
    
    // Если это другой пользователь, очищаем чаты
    if (currentUserId && currentUserId !== newUserId) {
      localStorage.removeItem("giga_agent_chat_history");
    }
    
    setToken(data.token);
    setUser({
      user_id: data.user_id,
      username: data.username,
      email: data.email,
    });

    // Сохраняем в localStorage
    localStorage.setItem("auth_token", data.token);
    localStorage.setItem("auth_user", JSON.stringify({
      user_id: data.user_id,
      username: data.username,
      email: data.email,
    }));
    
    // ВАЖНО: Создаем сеанс в Redis ДО создания потока
    try {
      const { createRedisSession } = await import("../../utils/redisApi");
      const redisResult = await createRedisSession(data.token);
      console.log(`✅ Redis сеанс создан при авторизации: ${redisResult.message}`);
      console.log(`   user_id: ${data.user_id}`);
    } catch (error) {
      console.error("⚠️ Не удалось создать сеанс в Redis при авторизации:", error);
      // Не прерываем процесс логина, если Redis недоступен
    }
  };

  const logout = async () => {
    if (token) {
      try {
        await fetch(`${API_BASE}/auth/logout`, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
          },
        });
      } catch (error) {
        console.error("Ошибка выхода:", error);
      }
    }

    setToken(null);
    setUser(null);
    localStorage.removeItem("auth_token");
    localStorage.removeItem("auth_user");
    // Очищаем чаты при выходе
    localStorage.removeItem("giga_agent_chat_history");
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        loading,
        login,
        logout,
        isAuthenticated: !!user && !!token,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
};

