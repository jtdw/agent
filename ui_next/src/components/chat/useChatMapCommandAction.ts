import type { ChatMessage } from '@/lib/api';
import { parseMapTextCommand, type ParsedMapTextCommand } from '../mapTextCommands';

type UseChatMapCommandActionArgs = {
  onMapTextCommand?: (command: ParsedMapTextCommand) => string;
  setMessages: (updater: (messages: ChatMessage[]) => ChatMessage[]) => void;
};

export function useChatMapCommandAction({
  onMapTextCommand,
  setMessages,
}: UseChatMapCommandActionArgs) {
  const handleMapCommand = (text: string) => {
    const mapCommand = parseMapTextCommand(text);
    if (!mapCommand || !onMapTextCommand) return false;
    const reply = onMapTextCommand(mapCommand);
    setMessages((messages) => [
      ...messages,
      { role: 'user', content: text },
      { role: 'assistant', content: reply || '地图操作已完成。' },
    ]);
    return true;
  };

  return { handleMapCommand };
}
