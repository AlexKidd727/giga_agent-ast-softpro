import React from "react";
import styled from "styled-components";
import { useNavigate } from "react-router-dom";
import {
  Check,
  ChevronRight,
  Plus,
  Printer,
  Files,
  Settings as SettingsIcon,
} from "lucide-react";
import LogoImage from "../assets/logo.png";
import LogoWhiteImage from "../assets/logo-white.png";
import QRImage from "../assets/qr.png";
import { useSettings } from "./Settings.tsx";
import { useDarkMode } from "@/hooks/use-dark-mode.tsx";
import { ragEnabled } from "@/components/rag/utils.ts";

const SIDEBAR_WIDTH = 250;

const Sidebar = styled.div<{ isOpen: boolean }>`
  position: fixed;
  top: 0;
  left: 0;
  width: ${SIDEBAR_WIDTH}px;
  height: 100%;
  padding: 20px;
  backdrop-filter: blur(20px);
  // box-shadow: 0 0 ${(props) => (props.isOpen ? "50px" : `0`)} #00000075;
  border-radius: 0 8px 8px 0;
  z-index: 100;
  transform: translateX(
    ${(props) => (props.isOpen ? "0" : `-${SIDEBAR_WIDTH}px`)}
  );
  transition:
    transform 0.3s ease,
    box-shadow 0.3s ease;
  @media (max-width: 900px) {
    border-radius: 0;
  }

  @media print {
    display: none;
  }
`;

const Overlay = styled.div<{ isOpen: boolean }>`
  display: none;

  /* показываем оверлей только на мобильных */
  @media (max-width: 900px) {
    display: ${(props) => (props.isOpen ? "block" : "none")};
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0, 0, 0, 0.5);
    z-index: 50;
  }

  @media print {
    display: none;
  }
`;

const Main = styled.div<{ isOpen: boolean }>`
  display: flex;
  height: 100vh;
  width: 100%;
  margin: 0 auto;
  transition: margin-left 0.3s ease;

  /* на больших экранах сдвигаем, на малых — нет */
  @media (max-width: 900px) {
    max-height: calc(100vh - 75px);
  }
  @media (min-width: 900px) {
    margin-left: ${(props) => (props.isOpen ? `${SIDEBAR_WIDTH}px` : "0")};
  }

  @media print {
    margin-left: 0 !important;
  }
`;

const Opener = styled.button<{ isOpen: boolean }>`
  position: fixed;
  top: 20px;
  left: 20px;
  z-index: 200;
  background: none;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  color: #fff;
  transition: left 0.3s ease;

  @media print {
    & svg {
      display: none;
    }
  }
`;

const Logo = styled.div<{ $isDark: boolean; $isOpen: boolean }>`
  width: ${({ $isOpen }) => ($isOpen ? "156px" : "40px")};
  height: 40px;
  transition: width 0.3s ease;
  background-image: url("${({ $isDark }) =>
    $isDark ? LogoImage : LogoWhiteImage}");
  background-size: cover;
`;

const QR = styled.div`
  width: 150px;
  height: 150px;
  margin-top: 8px;
  background-image: url(${QRImage});
  background-size: cover;
`;

const MenuItem = styled.div`
  display: flex;
  align-items: center;
  padding: 8px;
  font-size: 14px;
  border-radius: 8px;
  cursor: pointer;
  &:hover {
    background-color: rgba(255, 255, 255, 0.1);
  }
  svg {
    margin-right: 0.5rem;
  }
`;

const CheckboxContainer = styled.label`
  display: flex;
  align-items: center;
  padding: 8px;
  cursor: pointer;
  font-size: 14px;
`;

const HiddenCheckbox = styled.input.attrs({ type: "checkbox" })`
  border: 0;
  clip: rect(0 0 0 0);
  clippath: inset(50%);
  height: 1px;
  margin: -1px;
  overflow: hidden;
  padding: 0;
  position: absolute;
  white-space: nowrap;
  width: 1px;
`;

const StyledCheckbox = styled.div<{ checked: boolean }>`
  width: 16px;
  height: 16px;
  background: ${(p) => (p.checked ? "#4caf50" : "#555")};
  border-radius: 4px;
  transition: all 150ms;
  display: flex;
  align-items: center;
  justify-content: center;
  svg {
    visibility: ${(p) => (p.checked ? "visible" : "hidden")};
  }
`;

interface SidebarProps {
  children: React.ReactNode;
  onNewChat: () => void;
}

const SidebarComponent = ({ children, onNewChat }: SidebarProps) => {
  const navigate = useNavigate();
  const { settings, setSettings } = useSettings();
  const isDarkMode = useDarkMode();

  const toggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    setSettings({ ...settings, ...{ sideBarOpen: !settings.sideBarOpen } });
  };

  const handlePrint = (e: React.MouseEvent) => {
    e.stopPropagation();
    window.print();
  };

  const handleSettings = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigate("/demo/settings");
  };

  const handleRag = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigate("/rag");
  };

  const handleAutoApproveChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setSettings({ ...settings, ...{ autoApprove: e.target.checked } });
  };

  const handleNewChat = () => {
    navigate("/");
    onNewChat();
  };

  return (
    <>
      <Overlay isOpen={settings.sideBarOpen} onClick={toggle} />
      <Sidebar
        isOpen={settings.sideBarOpen}
        className={"bg-card border text-card-foreground"}
      >
        <Logo
          style={{ opacity: 0, marginBottom: "0.5rem" }}
          $isDark={isDarkMode}
          $isOpen={settings.sideBarOpen}
        />
        <MenuItem onClick={handleNewChat}>
          <Plus size={24} />
          Новый чат
        </MenuItem>
        <MenuItem onClick={handlePrint}>
          <Printer size={24} />
          Печать
        </MenuItem>
        {ragEnabled() && (
          <MenuItem onClick={handleRag}>
            <Files size={24} />
            База знаний
          </MenuItem>
        )}
        <MenuItem onClick={handleSettings}>
          <SettingsIcon size={24} />
          Настройки демо
        </MenuItem>
        <CheckboxContainer>
          <HiddenCheckbox
            checked={settings.autoApprove ?? false}
            onChange={handleAutoApproveChange}
          />
          <StyledCheckbox checked={settings.autoApprove ?? false}>
            <Check size={12} />
          </StyledCheckbox>
          <span style={{ marginLeft: 8 }}>Auto Approve</span>
        </CheckboxContainer>
        <QR />
      </Sidebar>

      <Opener isOpen={settings.sideBarOpen} onClick={toggle}>
        <Logo $isDark={isDarkMode} $isOpen={settings.sideBarOpen} />
        <ChevronRight
          style={{
            transform: settings.sideBarOpen ? "rotate(180deg)" : "rotate(0)",
            marginLeft: "0.3rem",
          }}
        />
      </Opener>

      <Main isOpen={settings.sideBarOpen}>{children}</Main>
    </>
  );
};

export default SidebarComponent;
