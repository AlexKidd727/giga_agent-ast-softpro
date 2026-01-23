import { useState } from "react";
import BrowserAuthModal from "@/components/modals/browser-auth-modal";

interface UseBrowserAuthOptions {
  onSuccess?: (cookies: string, sessionId: string) => void;
}

/**
 * Хук для работы с ручной авторизацией на сайтах через browser-service
 */
export function useBrowserAuth(options: UseBrowserAuthOptions = {}) {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [siteUrl, setSiteUrl] = useState("");
  const [sessionId, setSessionId] = useState("default");

  const openAuthModal = (url: string, session: string = "default") => {
    setSiteUrl(url);
    setSessionId(session);
    setIsModalOpen(true);
  };

  const closeAuthModal = () => {
    setIsModalOpen(false);
  };

  const handleSuccess = (cookies: string, session: string) => {
    if (options.onSuccess) {
      options.onSuccess(cookies, session);
    }
    closeAuthModal();
  };

  const AuthModal = () => (
    <BrowserAuthModal
      isOpen={isModalOpen}
      onClose={closeAuthModal}
      onSuccess={handleSuccess}
      siteUrl={siteUrl}
      sessionId={sessionId}
    />
  );

  return {
    openAuthModal,
    closeAuthModal,
    AuthModal,
  };
}
