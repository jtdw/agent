import { useEffect, useRef } from 'react';
import type { ExternalPromptCommand } from '../ChatPanel';

type UseChatExternalPromptArgs = {
  externalPrompt?: ExternalPromptCommand | null;
  sendPrompt: (prompt: string) => void;
};

export function useChatExternalPrompt({ externalPrompt, sendPrompt }: UseChatExternalPromptArgs) {
  const sendPromptRef = useRef(sendPrompt);

  useEffect(() => {
    sendPromptRef.current = sendPrompt;
  }, [sendPrompt]);

  useEffect(() => {
    if (externalPrompt?.prompt) sendPromptRef.current(externalPrompt.prompt);
  }, [externalPrompt?.id]);
}
