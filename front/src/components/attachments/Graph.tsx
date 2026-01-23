import React, { useEffect, useMemo, useState, useCallback } from "react";
import { useDarkMode } from "@/hooks/use-dark-mode.tsx";
import styled from "styled-components";
import { useSelectedAttachments } from "../../hooks/SelectedAttachmentsContext.tsx";
import { Check, X, Download, ZoomIn, ZoomOut } from "lucide-react";
// @ts-ignore
import createPlotlyComponent from "react-plotly.js/factory";
// @ts-ignore
import Plotly from "plotly.js-dist-min";

const Plot = createPlotlyComponent(Plotly);
import axios from "axios";

const Placeholder = styled.div`
  width: 100%;
  padding-top: 56.25%; /* подложка под изображение, чтобы не прыгал layout */
  background-color: #2d2d2d;
  position: relative;
`;

const Img = styled.img`
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
`;

const PlotWrapper = styled.div`
  .modebar-container,
  .modebar .modebar-group {
    background: rgba(0, 0, 0, 0) !important;
  }
`;

const SelectableContainer = styled.div`
  position: relative;
`;

const SelectorButton = styled.button<{ $selected: boolean; $isGraph: boolean }>`
  position: absolute;
  top: ${({ $isGraph }) => ($isGraph ? "40px" : "8px")};
  right: 8px;
  width: 24px;
  height: 24px;
  z-index: 1000;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  background-color: ${({ $selected }) =>
    $selected ? "#1976d2" : "transparent"};
  border: ${({ $selected }) =>
    $selected ? "1px solid #1976d2" : "1px solid #fff"};
  color: #fff;
  box-shadow: 0 0 0 2px rgba(0, 0, 0, 0.2);
  @media print {
    display: none;
  }

  &:hover {
    transform: scale(1.05);
  }
`;

// Контейнер для PNG изображения графика
const ImageContainer = styled.div`
  position: relative;
  width: 100%;
`;

const ChartImage = styled.img`
  width: 100%;
  max-height: 400px;
  object-fit: contain;
  display: block;
  cursor: zoom-in;
  transition: opacity 0.2s;

  &:hover {
    opacity: 0.9;
  }
`;

const DownloadLink = styled.a`
  display: inline-block;
  margin-top: 8px;
  color: #1976d2;
  text-decoration: underline;
  font-size: 14px;
  
  &:hover {
    color: #1565c0;
  }
`;

// Стили для модального окна
const ModalOverlay = styled.div`
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.9);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10000;
  cursor: zoom-out;
`;

const ModalContent = styled.div`
  position: relative;
  max-width: 95vw;
  max-height: 95vh;
  display: flex;
  align-items: center;
  justify-content: center;
`;

const ModalImage = styled.img<{ $scale: number }>`
  max-width: 95vw;
  max-height: 90vh;
  object-fit: contain;
  transform: scale(${({ $scale }) => $scale});
  transition: transform 0.2s ease;
  cursor: default;
`;

const ModalToolbar = styled.div`
  position: fixed;
  top: 20px;
  right: 20px;
  display: flex;
  gap: 10px;
  z-index: 10001;
`;

const ToolbarButton = styled.button`
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: none;
  background-color: rgba(255, 255, 255, 0.2);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background-color 0.2s;

  &:hover {
    background-color: rgba(255, 255, 255, 0.4);
  }
`;

interface GraphProps {
  id: string;
  alt?: string;
  data: any;
}

// Интерфейс для данных giga_attachments
interface GigaAttachment {
  type: string;
  file_id?: string;
  data?: string; // base64 данные
  path?: string; // путь к файлу
  file_size?: number;
}

// Интерфейс для результата функции tinkoff_agent
interface FunctionResult {
  data?: {
    giga_attachments?: GigaAttachment[];
    message?: string;
    status?: string;
  };
  message?: string;
  model_name?: string;
}

// Проверка, является ли объект данными Plotly
const isPlotlyData = (obj: any): boolean => {
  if (!obj) return false;
  // Plotly данные обычно имеют массив data и объект layout
  return Array.isArray(obj.data) && obj.layout !== undefined;
};

// Проверка, является ли объект результатом функции с giga_attachments
const isFunctionResultWithAttachments = (obj: any): obj is FunctionResult => {
  if (!obj) return false;
  // Результат функции имеет структуру { data: { giga_attachments: [...] } }
  return obj.data && Array.isArray(obj.data.giga_attachments);
};

const Graph: React.FC<GraphProps> = ({ id, alt, data }) => {
  const [fig, setFig] = useState<any>(null);
  const [imageData, setImageData] = useState<{ src: string; downloadPath: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [scale, setScale] = useState(1);

  const openModal = useCallback(() => {
    setIsModalOpen(true);
    setScale(1);
  }, []);

  const closeModal = useCallback(() => {
    setIsModalOpen(false);
    setScale(1);
  }, []);

  const handleZoomIn = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    setScale((prev) => Math.min(prev + 0.25, 3));
  }, []);

  const handleZoomOut = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    setScale((prev) => Math.max(prev - 0.25, 0.5));
  }, []);

  const handleDownload = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    if (imageData) {
      const link = document.createElement('a');
      link.href = imageData.src;
      link.download = alt || `chart-${id}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    }
  }, [imageData, alt, id]);

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      closeModal();
    } else if (e.key === '+' || e.key === '=') {
      setScale((prev) => Math.min(prev + 0.25, 3));
    } else if (e.key === '-') {
      setScale((prev) => Math.max(prev - 0.25, 0.5));
    }
  }, [closeModal]);

  // Добавляем обработчик клавиш при открытии модального окна
  useEffect(() => {
    if (isModalOpen) {
      document.addEventListener('keydown', handleKeyDown);
      document.body.style.overflow = 'hidden';
      return () => {
        document.removeEventListener('keydown', handleKeyDown);
        document.body.style.overflow = '';
      };
    }
  }, [isModalOpen, handleKeyDown]);
  
  useEffect(() => {
    // Проверяем, что data.path существует и является строкой
    if (!data || !data.path || typeof data.path !== "string") {
      console.error("[Graph] Invalid data.path:", data?.path, "type:", typeof data?.path);
      setError("Некорректный путь к графику");
      return;
    }
    
    // Нормализуем путь - убираем дублирование /files/
    let normalizedPath = data.path;
    // Если путь уже начинается с /files/, используем его напрямую
    if (normalizedPath.startsWith("/files/")) {
      // Путь уже содержит /files/, используем как есть
    } else if (normalizedPath.startsWith("/")) {
      // Путь начинается с /, добавляем /files
      normalizedPath = "/files" + normalizedPath;
    } else {
      // Путь не начинается с /, добавляем /files/
      normalizedPath = "/files/" + normalizedPath;
    }
    
    const url = `${window.location.protocol}//${window.location.host}${normalizedPath}`;
    console.log("[Graph] Loading graph from:", url);
    
    axios
      .get(url)
      .then((res) => {
        const responseData = res.data;
        console.log("[Graph] Received data type:", typeof responseData, "keys:", responseData ? Object.keys(responseData) : "null");
        
        // Проверяем тип данных
        if (isFunctionResultWithAttachments(responseData)) {
          // Это результат функции с giga_attachments (например, от tinkoff_agent)
          console.log("[Graph] Detected function result with giga_attachments");
          const attachments = responseData.data?.giga_attachments || [];
          const imageAttachment = attachments.find(
            (att: GigaAttachment) => att.type === "image/png" || att.type?.startsWith("image/")
          );
          
          if (imageAttachment) {
            let imgSrc = "";
            let downloadPath = "";
            
            // Если есть путь к файлу, используем его
            if (imageAttachment.path && typeof imageAttachment.path === "string") {
              let imgPath = imageAttachment.path;
              // Нормализуем путь
              if (!imgPath.startsWith("/files/") && !imgPath.startsWith("http")) {
                if (imgPath.startsWith("/")) {
                  imgPath = "/files" + imgPath;
                } else {
                  imgPath = "/files/" + imgPath;
                }
              }
              imgSrc = `${window.location.protocol}//${window.location.host}${imgPath}`;
              downloadPath = imgPath;
              console.log("[Graph] Using image path:", imgSrc);
            } else if (imageAttachment.data) {
              // Если есть base64 данные, используем их
              imgSrc = `data:${imageAttachment.type};base64,${imageAttachment.data}`;
              downloadPath = "";
              console.log("[Graph] Using base64 image data");
            }
            
            if (imgSrc) {
              setImageData({ src: imgSrc, downloadPath });
              setFig(null);
              setError(null);
              return;
            }
          }
          
          // Если не нашли изображение в attachments
          setError("Не найдено изображение в данных");
        } else if (isPlotlyData(responseData)) {
          // Это данные Plotly
          console.log("[Graph] Detected Plotly data");
          setFig(responseData);
          setImageData(null);
          setError(null);
        } else {
          console.error("[Graph] Unknown data format:", responseData);
          setError("Неизвестный формат данных графика");
        }
      })
      .catch((err) => {
        console.error("[Graph] Error loading graph:", err, "URL:", url);
        setError("Ошибка загрузки графика");
      });
  }, [data?.path]);

  const isDark = useDarkMode();
  const { isSelected, toggle } = useSelectedAttachments();
  const selected = isSelected(id);
  const layout = useMemo(() => {
    if (!fig) return null;
    if (isDark) {
      return {
        ...fig.layout,
        template: "plotly_dark",
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: "rgba(0,0,0,0)",
        font: { color: "#fff" },
        xaxis: {
          ...fig.layout?.xaxis,
          gridcolor: "rgba(255,255,255,0.2)",
          zerolinecolor: "rgba(255,255,255,0.2)",
        },
        yaxis: {
          ...fig.layout?.yaxis,
          gridcolor: "rgba(255,255,255,0.2)",
          zerolinecolor: "rgba(255,255,255,0.2)",
        },
      };
    }
    return {
      ...fig.layout,
      template: "plotly_white",
      paper_bgcolor: "rgba(255,255,255,0)",
      plot_bgcolor: "rgba(255,255,255,0)",
      font: { color: "#111" },
      xaxis: {
        ...fig.layout?.xaxis,
        gridcolor: "rgba(0,0,0,0.15)",
        zerolinecolor: "rgba(0,0,0,0.15)",
      },
      yaxis: {
        ...fig.layout?.yaxis,
        gridcolor: "rgba(0,0,0,0.15)",
        zerolinecolor: "rgba(0,0,0,0.15)",
      },
    };
  }, [fig, isDark]);
  
  if (error) return <div className="text-red-500 p-4">{error}</div>;
  
  // Если есть PNG изображение (результат tinkoff_agent)
  if (imageData) {
    return (
      <>
        <SelectableContainer>
          <SelectorButton
            aria-label="select-attachment"
            $isGraph={false}
            $selected={selected}
            onClick={(e) => {
              e.stopPropagation();
              toggle(id, alt);
            }}
          >
            {selected ? <Check size={24} /> : null}
          </SelectorButton>
          <ImageContainer>
            <ChartImage 
              src={imageData.src} 
              alt={alt || "Chart"} 
              onClick={openModal}
            />
            {imageData.downloadPath && (
              <DownloadLink 
                href={imageData.src} 
                target="_blank" 
                rel="noopener noreferrer"
                download
              >
                Скачать график
              </DownloadLink>
            )}
          </ImageContainer>
        </SelectableContainer>

        {/* Модальное окно для просмотра графика */}
        {isModalOpen && (
          <ModalOverlay onClick={closeModal}>
            <ModalToolbar>
              <ToolbarButton onClick={handleZoomOut} title="Уменьшить (-)">
                <ZoomOut size={20} />
              </ToolbarButton>
              <ToolbarButton onClick={handleZoomIn} title="Увеличить (+)">
                <ZoomIn size={20} />
              </ToolbarButton>
              <ToolbarButton onClick={handleDownload} title="Скачать">
                <Download size={20} />
              </ToolbarButton>
              <ToolbarButton onClick={closeModal} title="Закрыть (Esc)">
                <X size={20} />
              </ToolbarButton>
            </ModalToolbar>
            <ModalContent onClick={(e) => e.stopPropagation()}>
              <ModalImage
                src={imageData.src}
                alt={alt || "Chart"}
                $scale={scale}
              />
            </ModalContent>
          </ModalOverlay>
        )}
      </>
    );
  }
  
  if (!fig) return <Placeholder />;
  
  return (
    <SelectableContainer>
      <SelectorButton
        aria-label="select-attachment"
        $isGraph={true}
        $selected={selected}
        onClick={(e) => {
          e.stopPropagation();
          toggle(id, alt);
        }}
      >
        {selected ? <Check size={24} /> : null}
      </SelectorButton>
      <PlotWrapper>
        <Plot
          data={fig.data}
          layout={layout}
          useResizeHandler
          style={{ width: "100%" }}
        />
      </PlotWrapper>
    </SelectableContainer>
  );
};

export default Graph;
