import React from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export const ToolsTab: React.FC = () => {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Инструменты</CardTitle>
        <CardDescription>
          Управление инструментами и MCP серверами
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="text-sm text-muted-foreground">
          Информация о MCP серверах доступна только администраторам в разделе{" "}
          <strong>«Админка → MCP Серверы»</strong>.
        </div>
        <div className="text-sm text-muted-foreground">
          MCP подключается на сервере при старте (конфигурация хранится в БД, таблица <code>mcp_server</code>),
          без браузерных подключений и без CORS.
        </div>
      </CardContent>
    </Card>
  );
};

