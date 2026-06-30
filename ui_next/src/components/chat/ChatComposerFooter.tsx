import { ChatComposer } from '../ChatComposer';
import { cn } from '@/lib/cn';
import type { WorkspaceMention } from '@/lib/api';

type ChatComposerFooterProps = {
  isPage: boolean;
  thinking: boolean;
  userId: string;
  input: string;
  setInput: (value: string) => void;
  send: () => void;
  uploadFiles: (files: FileList | File[]) => void;
  stopCurrentRequest: () => void;
  uploading: boolean;
  voiceSupported: boolean;
  listening: boolean;
  voiceUnavailableReason: string;
  toggleVoice: () => void;
  workspaceMentions: WorkspaceMention[];
};

export function ChatComposerFooter({
  isPage,
  thinking,
  userId,
  input,
  setInput,
  send,
  uploadFiles,
  stopCurrentRequest,
  uploading,
  voiceSupported,
  listening,
  voiceUnavailableReason,
  toggleVoice,
  workspaceMentions,
}: ChatComposerFooterProps) {
  return (
    <div
      data-testid="chat-composer-footer"
      className={cn('chat-composer-footer', isPage && 'lg:col-start-2 lg:row-start-3')}
      style={{ paddingBottom: 'max(1rem, env(safe-area-inset-bottom))' }}
    >
      <ChatComposer
        value={input}
        onChange={setInput}
        onSend={send}
        onUpload={uploadFiles}
        onStop={stopCurrentRequest}
        sending={thinking}
        uploading={uploading}
        disabled={!userId}
        voiceSupported={voiceSupported}
        listening={listening}
        voiceUnavailableReason={voiceUnavailableReason}
        onVoiceToggle={toggleVoice}
        mentionItems={workspaceMentions}
      />
    </div>
  );
}
