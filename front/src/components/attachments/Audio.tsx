import React from "react";

interface HTMLPageProps {
  id: string;
  data: any;
  alt?: string;
}

const Audio: React.FC<HTMLPageProps> = ({ data }) => {
  // Если есть base64 данные, используем их напрямую
  let audioSrc: string;
  if (data.data) {
    // data.data содержит base64 строку
    const mimeType = data.type || "audio/mp3";
    audioSrc = `data:${mimeType};base64,${data.data}`;
  } else if (data.path) {
    // Если есть path, используем его (для совместимости со старым форматом)
    audioSrc = `${window.location.protocol}//${window.location.host}/files${data.path}`;
  } else {
    return <div>Ошибка: нет данных для воспроизведения аудио</div>;
  }

  return (
    <audio
      controls={true}
      style={{ marginTop: "5px", marginBottom: "5px", display: "block" }}
    >
      <source src={audioSrc} />
    </audio>
  );
};

export default Audio;
