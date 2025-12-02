import { useEffect, useRef, useState } from "react";

export function useStableMessages(thread: any) {
  const [stableMessages, setStableMessages] = useState(thread.messages ?? []);
  const previousMessagesRef = useRef(thread.messages ?? []);

  useEffect(() => {
    if (!("__interrupt__" in thread.values) && thread.messages.length > 0) {
      // Обновляем, если пришли нормальные сообщения
      previousMessagesRef.current = thread.messages;
      setStableMessages(thread.messages);
      // @ts-ignore
      globalThis.messagesDebug = thread.messages;
    } else {
    }
  }, [thread.messages]);

  return stableMessages;
}
