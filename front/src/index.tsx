import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { GlobalStyle } from "./styles/GlobalStyle";
import "./style.css";

const root = ReactDOM.createRoot(
  document.getElementById("root") as HTMLElement,
);

try {
  root.render(
    <>
      <GlobalStyle />
      <App />
    </>
  );
  
  // Устанавливаем opacity сразу, чтобы контент был виден
  if (typeof window !== "undefined") {
    const rootElement = document.getElementById("root");
    if (rootElement) {
      rootElement.style.opacity = "1";
      rootElement.classList.remove("opacity-0");
    }
  }
} catch (error) {
  console.error("Error rendering app:", error);
  const rootElement = document.getElementById("root");
  if (rootElement) {
    rootElement.innerHTML = '<div style="padding: 20px; color: red;">Ошибка загрузки приложения. Проверьте консоль браузера.</div>';
    rootElement.style.opacity = "1";
  }
}
