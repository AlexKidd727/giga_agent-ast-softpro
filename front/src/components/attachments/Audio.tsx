import React from "react";
import { Download } from "lucide-react";

interface HTMLPageProps {
  id: string;
  data: any;
  alt?: string;
}

const Audio: React.FC<HTMLPageProps> = ({ data, id, alt }) => {
  // Если есть base64 данные, используем их напрямую
  let audioSrc: string;
  let downloadUrl: string;
  let fileName: string;
  
  if (data.data) {
    // data.data содержит base64 строку
    const mimeType = data.type || "audio/mp3";
    audioSrc = `data:${mimeType};base64,${data.data}`;
    // Для base64 создаем blob URL для загрузки
    const byteCharacters = atob(data.data);
    const byteNumbers = new Array(byteCharacters.length);
    for (let i = 0; i < byteCharacters.length; i++) {
      byteNumbers[i] = byteCharacters.charCodeAt(i);
    }
    const byteArray = new Uint8Array(byteNumbers);
    const blob = new Blob([byteArray], { type: mimeType });
    downloadUrl = URL.createObjectURL(blob);
    fileName = alt || `audio_${id}.${mimeType.split('/')[1] || 'mp3'}`;
  } else if (data.path) {
    // Если есть path, используем его (для совместимости со старым форматом)
    const path = data.path.startsWith('/files/') ? data.path : `/files${data.path}`;
    audioSrc = `${window.location.protocol}//${window.location.host}${path}`;
    downloadUrl = audioSrc;
    fileName = alt || data.path.split('/').pop() || `audio_${id}.mp3`;
  } else {
    return <div>Ошибка: нет данных для воспроизведения аудио</div>;
  }

  const handleDownload = () => {
    const link = document.createElement('a');
    link.href = downloadUrl;
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    // Освобождаем blob URL если он был создан
    if (data.data && downloadUrl.startsWith('blob:')) {
      URL.revokeObjectURL(downloadUrl);
    }
  };

  return (
    <div style={{ position: "relative", marginTop: "5px", marginBottom: "5px" }}>
      <audio
        controls={true}
        style={{ display: "block", width: "100%" }}
      >
        <source src={audioSrc} />
      </audio>
      <button
        onClick={handleDownload}
        style={{
          marginTop: "8px",
          padding: "6px 12px",
          backgroundColor: "transparent",
          border: "1px solid currentColor",
          borderRadius: "4px",
          cursor: "pointer",
          display: "inline-flex",
          alignItems: "center",
          gap: "6px",
          fontSize: "14px",
        }}
        title="Скачать аудио"
      >
        <Download size={16} />
        Скачать
      </button>
    </div>
  );
};

export default Audio;
