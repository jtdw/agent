import { MessageSquare, Wrench } from 'lucide-react';
import { ChatComposer } from '../ChatComposer';
import { cn } from '@/lib/cn';
import type { WorkspaceMention } from '@/lib/api';

type InteractionMode = 'chat_only' | 'tool_enabled';

type ChatComposerFooterProps = {
  isPage: boolean;
  currentInteractionMode: InteractionMode;
  setInteractionMode: (mode: InteractionMode) => void;
  interactionModeLabel: string;
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
  currentInteractionMode,
  setInteractionMode,
  interactionModeLabel,
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
      className={cn('chat-composer-footer', isPage ? 'is-page' : 'is-floating', isPage && 'lg:col-start-2 lg:row-start-3')}
      style={{ paddingBottom: 'max(1rem, env(safe-area-inset-bottom))' }}
    >
      <div className="chat-composer-footer-meta">
        <div className="chat-composer-mode-panel" aria-label="会话交互模式">
          <div className="chat-interaction-mode-switch" aria-label="会话模式">
            <button
              type="button"
              data-testid="interaction-mode-chat"
              className={cn('chat-interaction-mode-button', currentInteractionMode === 'chat_only' && 'is-active is-chat')}
              title="聊天模式：只回答问题，不操作数据"
              aria-pressed={currentInteractionMode === 'chat_only'}
              disabled={thinking || !userId}
              onClick={() => setInteractionMode('chat_only')}
            >
              <MessageSquare size={14} /> 聊天
            </button>
            <button
              type="button"
              data-testid="interaction-mode-tool"
              className={cn('chat-interaction-mode-button', currentInteractionMode === 'tool_enabled' && 'is-active is-tool')}
              title="工具模式：经计划和校验后执行工具"
              aria-pressed={currentInteractionMode === 'tool_enabled'}
              disabled={thinking || !userId}
              onClick={() => setInteractionMode('tool_enabled')}
            >
              <Wrench size={14} /> 工具
            </button>
          </div>
          <div className="chat-composer-mode-copy">{interactionModeLabel}</div>
        </div>
      </div>
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
