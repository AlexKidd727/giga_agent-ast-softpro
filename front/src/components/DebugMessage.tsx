/**
 * Компонент для отображения отладочных сообщений в чате
 * Показывается только когда включен режим отладки
 */
import React from "react";

interface DebugMessageProps {
  message: string;
  type?: "info" | "success" | "warning" | "error";
}

const DebugMessage: React.FC<DebugMessageProps> = ({ message, type = "info" }) => {
  const getColorClass = () => {
    switch (type) {
      case "success":
        return "bg-green-500/20 border-green-500/50 text-green-300";
      case "warning":
        return "bg-yellow-500/20 border-yellow-500/50 text-yellow-300";
      case "error":
        return "bg-red-500/20 border-red-500/50 text-red-300";
      default:
        return "bg-blue-500/20 border-blue-500/50 text-blue-300";
    }
  };

  const getIcon = () => {
    switch (type) {
      case "success":
        return "✅";
      case "warning":
        return "⚠️";
      case "error":
        return "❌";
      default:
        return "ℹ️";
    }
  };

  return (
    <div className={`flex items-start mb-2 px-9`}>
      <div
        className={`flex flex-col border border-2 ${getColorClass()} p-3 rounded-lg flex-1 max-w-full text-sm`}
      >
        <div className="flex items-center">
          <span className="mr-2">{getIcon()}</span>
          <span className="font-mono text-xs opacity-75">[DEBUG]</span>
        </div>
        <div className="mt-1">{message}</div>
      </div>
    </div>
  );
};

export default DebugMessage;

