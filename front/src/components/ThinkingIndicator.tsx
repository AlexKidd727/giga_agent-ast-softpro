// ThinkingIndicator.tsx
import React from "react";
import styled, { keyframes } from "styled-components";
import { Message as Message_ } from "@langchain/langgraph-sdk";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { GraphState } from "../interfaces.ts";

// Анимация перемещения фона слева направо
const shimmer = keyframes`
  0% { background-position: -100% 0; }
  100% { background-position: 200% 0; }
`;

// Анимация плавного появления
const fadeIn = keyframes`
  from { opacity: 0; }
  to { opacity: 1; }
`;

// Стили для переливающегося текста
const Thinking = styled.div`
  color: transparent;
  // вертикальная светлая линия
  background-size: 50% 100%;
  background: linear-gradient(
    90deg,
    rgba(255, 255, 255, 0.3) 0%,
    rgba(255, 255, 255, 0.9) 50%,
    rgba(255, 255, 255, 0.3) 100%
  ); // вертикальная светлая линия
  background-size: 50% 100%;
  background-repeat: repeat;
  background-position: -100% 0;
  background-clip: text;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  padding: 10px 34px;

  animation:
    ${fadeIn} 0.5s ease-out,
    ${shimmer} 3.5s linear infinite;
`;

interface ThinkingProps {
  messages: Message_[];
  thread?: UseStream<GraphState>;
}

const ThinkingIndicator = ({ messages, thread }: ThinkingProps) => {
  if (
    messages.length <= 0 ||
    messages[messages.length - 1].type === "ai" ||
    !thread?.isLoading
  ) {
    return null;
  }
  return <Thinking>Думаю…</Thinking>;
};

export default ThinkingIndicator;
