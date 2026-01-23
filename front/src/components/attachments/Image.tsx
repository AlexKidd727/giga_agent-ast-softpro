import React, { useState, useCallback } from "react";
import styled from "styled-components";
import { useSelectedAttachments } from "../../hooks/SelectedAttachmentsContext.tsx";
import { Check, X, Download, ZoomIn, ZoomOut } from "lucide-react";

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

const ThumbnailImage = styled.img`
  max-width: 100%;
  max-height: 300px;
  border-radius: 4px;
  cursor: zoom-in;
  transition: opacity 0.2s;

  &:hover {
    opacity: 0.9;
  }
`;

interface ImageProps {
  id: string;
  data: any;
  alt?: string;
}

const Image: React.FC<ImageProps> = ({ id, data, alt }) => {
  const { isSelected, toggle } = useSelectedAttachments();
  const selected = isSelected(id);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [scale, setScale] = useState(1);

  // Определяем источник изображения
  // Если есть base64 данные, используем их напрямую
  // Иначе используем путь к файлу
  let imageSrc: string;
  if (data.data && typeof data.data === 'string' && data.data.length > 0) {
    // Используем base64 данные напрямую
    // Определяем MIME тип из данных или используем PNG по умолчанию
    const mimeType = data.type || 'image/png';
    imageSrc = `data:${mimeType};base64,${data.data}`;
  } else if (data.path && typeof data.path === 'string') {
    // Используем путь к файлу
    // Нормализуем путь: если начинается с /files/, используем напрямую
    // Если начинается с /home/jupyter, преобразуем в /files/
    let normalizedPath = data.path;
    if (data.path.startsWith('/home/jupyter')) {
      normalizedPath = data.path.replace('/home/jupyter', '/files');
    } else if (!data.path.startsWith('/files/') && !data.path.startsWith('/')) {
      normalizedPath = `/files/${data.path}`;
    } else if (!data.path.startsWith('/files/')) {
      normalizedPath = `/files${data.path}`;
    }
    imageSrc = `${window.location.protocol}//${window.location.host}${normalizedPath}`;
  } else {
    // Fallback: используем file_id как путь
    imageSrc = `${window.location.protocol}//${window.location.host}/files/${id}`;
  }

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
    const link = document.createElement('a');
    link.href = imageSrc;
    link.download = alt || `image-${id}`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }, [imageSrc, alt, id]);

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
  React.useEffect(() => {
    if (isModalOpen) {
      document.addEventListener('keydown', handleKeyDown);
      document.body.style.overflow = 'hidden';
      return () => {
        document.removeEventListener('keydown', handleKeyDown);
        document.body.style.overflow = '';
      };
    }
  }, [isModalOpen, handleKeyDown]);

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
        <div style={{ display: "flex" }}>
          <ThumbnailImage
            src={imageSrc}
            alt={`attachment-${alt || id}`}
            onClick={openModal}
            onError={(e) => {
              const imgElement = e.target as HTMLImageElement;
              // Если загрузка по пути не удалась, пробуем base64
              if (data.data && typeof data.data === 'string' && data.data.length > 0) {
                const mimeType = data.type || 'image/png';
                imgElement.src = `data:${mimeType};base64,${data.data}`;
              } else {
                // Пробуем альтернативные пути
                if (data.path && typeof data.path === 'string') {
                  // Пробуем путь без /files/ префикса
                  if (data.path.startsWith('/files/')) {
                    const altPath = data.path.replace('/files/', '/');
                    imgElement.src = `${window.location.protocol}//${window.location.host}${altPath}`;
                  } else {
                    // Пробуем добавить /files/ если его нет
                    imgElement.src = `${window.location.protocol}//${window.location.host}/files/${data.path}`;
                  }
                } else {
                  console.error(`Ошибка загрузки изображения: path=${data.path}, has_data=${!!data.data}, data_size=${data.data ? data.data.length : 0}, id=${id}`);
                  // Показываем placeholder вместо скрытия
                  imgElement.style.display = 'none';
                  imgElement.parentElement!.innerHTML = '<div style="padding: 20px; text-align: center; color: #999;">Не удалось загрузить изображение</div>';
                }
              }
            }}
          />
        </div>
      </SelectableContainer>

      {/* Модальное окно для просмотра изображения */}
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
              src={imageSrc}
              alt={`attachment-${alt || id}`}
              $scale={scale}
            />
          </ModalContent>
        </ModalOverlay>
      )}
    </>
  );
};

export default Image;
