import React, { useEffect, useRef, useState } from "react";
import styled from "styled-components";
import { ChevronUp } from "lucide-react";
import axios from "axios";
import TextMarkdown from "./TextMarkdown.tsx";

const Placeholder = styled.div`
  width: 100%;
  padding-top: 56.25%; /* подложка под изображение, чтобы не прыгал layout */
  background-color: #2d2d2d;
  position: relative;
`;

const InnerText = styled.div`
  background: rgba(0, 0, 0, 0.08);
  border-radius: 8px;
`;

const InnerHeader = styled.div`
  padding: 1.33em 1em;
  border-bottom: 1px solid gray;
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  user-select: none;
`;

const InnerBody = styled.div<{ $maxHeightPx: number; $fade: boolean }>`
  padding: 0 1.5rem;
  overflow: hidden;
  transition: max-height 0.3s ease;
  max-height: ${(p) => `${p.$maxHeightPx}px`};
  /* плавное затухание текста к фону внизу при обрезке */
  -webkit-mask-image: ${(p) =>
    p.$fade
      ? "linear-gradient(to bottom, black 80%, transparent 100%)"
      : "none"};
  mask-image: ${(p) =>
    p.$fade
      ? "linear-gradient(to bottom, black 80%, transparent 100%)"
      : "none"};
`;

const Arrow = styled(ChevronUp)<{ $expanded: boolean }>`
  transition: transform 0.2s ease;
  transform: rotate(${(p) => (p.$expanded ? "180deg" : "0deg")});
`;

interface TextProps {
  id: string;
  alt?: string;
  data: any;
}

const Text: React.FC<TextProps> = ({ id, data }) => {
  const [text, setText] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [expanded, setExpanded] = useState<boolean>(false);
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const COLLAPSED_MAX = 320;
  const [maxHeight, setMaxHeight] = useState<number>(COLLAPSED_MAX);
  const [showFade, setShowFade] = useState<boolean>(true);
  useEffect(() => {
    axios
      .get(
        `${window.location.protocol}//${window.location.host}/files${data.path}`,
      )
      .then((res) => {
        setText(res.data);
        setLoading(false);
      })
      .catch(() => {
        setError(true);
      });
  }, [data.path]);
  if (loading) return <Placeholder />;
  if (error)
    return (
      <div>
        Ошибка загрузки вложения{" "}
        <a
          href={`${window.location.protocol}//${window.location.host}/files${data.path}`}
          target={"_blank"}
        >
          {id}
        </a>
      </div>
    );
  return (
    <InnerText>
      <InnerHeader
        onClick={() => {
          setExpanded((prev) => {
            const next = !prev;
            const el = bodyRef.current;
            if (!el) {
              setMaxHeight(COLLAPSED_MAX);
              return next;
            }
            if (next) {
              setShowFade(false);
              const start = Math.max(el.clientHeight, COLLAPSED_MAX);
              const end = el.scrollHeight;
              setMaxHeight(start);
              void el.offsetHeight; // force reflow
              requestAnimationFrame(() => {
                setMaxHeight(end);
              });
            } else {
              setShowFade(true);
              const start = el.clientHeight;
              setMaxHeight(start);
              void el.offsetHeight; // force reflow
              requestAnimationFrame(() => {
                setMaxHeight(COLLAPSED_MAX);
              });
            }
            return next;
          });
        }}
      >
        <h4 style={{ margin: 0 }}>
          Файл:{" "}
          <a
            href={`${window.location.protocol}//${window.location.host}/files${data.path}`}
            target={"_blank"}
          >
            {id}
          </a>
        </h4>
        <Arrow size={18} $expanded={expanded} />
      </InnerHeader>
      <InnerBody ref={bodyRef} $maxHeightPx={maxHeight} $fade={showFade}>
        <TextMarkdown>{text}</TextMarkdown>
      </InnerBody>
    </InnerText>
  );
};

export default Text;
