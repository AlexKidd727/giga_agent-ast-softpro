import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { GlobalStyle } from "./styles/GlobalStyle";
import "./style.css";

const root = ReactDOM.createRoot(
  document.getElementById("root") as HTMLElement,
);

root.render(
  <React.StrictMode>
    <>
      <GlobalStyle />
      <App />
    </>
  </React.StrictMode>,
);

if (typeof window !== "undefined") {
  // const preloader = document.getElementById("preloader");
  // if (preloader) {
  //   preloader.style.transition = "opacity 200ms";
  //   preloader.style.opacity = "0";
  //   // даём анимации закончиться, потом удаляем
  //   setTimeout(() => preloader.remove(), 200);
  // }
  const root = document.getElementById("root");
  if (root) root.style.opacity = "1";
}
