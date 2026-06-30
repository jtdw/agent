import type { RefObject } from 'react';
import { ChevronsLeft, MessageSquare, PlayCircle, Plus, Trash2, UploadCloud, Wrench } from 'lucide-react';
import type { ChatModelState, ChatSession } from '@/lib/api';
import { cn } from '@/lib/cn';
import { RealtimeSyncIndicator } from './RealtimeSyncIndicator';
import type { RealtimeSyncState } from './useChatRealtimeEvents';

type ChatModel = NonNullable<ChatModelState['models']>[number];
type InteractionMode = 'chat_only' | 'tool_enabled';

type ChatConversationHeaderProps = {
  isPage: boolean;
  currentSession?: ChatSession | null;
  currentSessionId: string;
  visibleSessions: ChatSession[];
  messagesLength: number;
  realtimeSyncState: RealtimeSyncState;
  onClose?: () => void;
  switchSession: (sessionId: string) => void;
  newSession: () => void;
  deleteSession: () => void;
  runThesisWorkflow: () => void;
  chatModels: ChatModelState | null;
  visibleModels: ChatModel[];
  modelLoading: boolean;
  modelNotice: string;
  modelError: string;
  thinking: boolean;
  userId: string;
  changeChatModel: (model: string) => void;
  uploading: boolean;
  fileInputRef: RefObject<HTMLInputElement | null>;
  uploadFiles: (files: FileList | null) => void;
  currentInteractionMode: InteractionMode;
  setInteractionMode: (mode: InteractionMode) => void;
  interactionModeLabel: string;
};

export function ChatConversationHeader({
  isPage,
  currentSession,
  currentSessionId,
  visibleSessions,
  messagesLength,
  realtimeSyncState,
  onClose,
  switchSession,
  newSession,
  deleteSession,
  runThesisWorkflow,
  chatModels,
  visibleModels,
  modelLoading,
  modelNotice,
  modelError,
  thinking,
  userId,
  changeChatModel,
  uploading,
  fileInputRef,
  uploadFiles,
  currentInteractionMode,
  setInteractionMode,
  interactionModeLabel,
}: ChatConversationHeaderProps) {
  const title = currentSession?.title || '新对话';
  const modelTitle = chatModels?.selected_model === 'auto'
    ? '自动选择：根据任务内容选择模型'
    : chatModels?.selected_model || '自动选择';

  const modelSelector = (className: string) => (
    <div className="relative min-w-0">
      <select
        data-testid="chat-model-selector"
        value={chatModels?.selected_model || 'auto'}
        onChange={(event) => changeChatModel(event.target.value)}
        disabled={!userId || !currentSessionId || modelLoading || thinking}
        className={className}
        title={modelTitle}
      >
        <option value="auto">自动选择</option>
        {visibleModels.map((model) => (
          <option key={model.id} value={model.id}>{model.id} · {model.capability === 'vision' ? '视觉' : '文本'}</option>
        ))}
      </select>
      {(modelNotice || modelError) && <span className={cn('chat-model-notice', modelError && 'is-error')}>{modelError || modelNotice}</span>}
    </div>
  );

  const modeSwitch = (className = '') => (
    <div className={cn('chat-header-mode-panel', className)} aria-label="会话交互模式">
      <div className="chat-interaction-mode-switch" aria-label="会话模式" title={interactionModeLabel}>
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
    </div>
  );

  return (
    <header data-testid="chat-conversation-header" className={cn('relative border-b border-slate-200/80 bg-white/82 shadow-[0_10px_30px_rgba(15,23,42,.04)] backdrop-blur-xl dark:border-slate-800 dark:bg-slate-900/78', isPage ? 'flex min-h-12 items-center gap-2 px-3 lg:col-start-2 lg:row-start-1' : 'flex flex-col gap-2 px-3 py-3')}>
      {!isPage ? (
        <>
          <div className="flex min-w-0 items-center gap-2">
            <div className="min-w-0 flex-1">
              <div className="flex min-w-0 items-center gap-2"><h1 className="truncate text-sm font-bold text-slate-950 dark:text-slate-50">{title}</h1><RealtimeSyncIndicator state={realtimeSyncState} /></div>
              <p className="mt-0.5 text-[11px] font-medium text-slate-400">{messagesLength} 条消息</p>
            </div>
            <button onClick={onClose} className="chat-icon-action" title="隐藏聊天" aria-label="隐藏聊天">
              <ChevronsLeft size={18} strokeWidth={1.7} />
            </button>
          </div>
          <div data-testid="floating-chat-toolbar" className="grid min-w-0 grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto_auto] gap-2">
            {visibleSessions.length > 0 ? (
              <select value={currentSessionId} onChange={(event) => switchSession(event.target.value)} disabled={thinking || modelLoading} className="chat-compact-select min-w-0">
                {visibleSessions.map((session) => <option key={session.session_id} value={session.session_id}>{session.title || '新对话'}</option>)}
              </select>
            ) : (
              <button onClick={newSession} disabled={thinking || modelLoading || !userId} className="chat-compact-select min-w-0 text-left">新对话</button>
            )}
            {modelSelector('chat-model-select w-full max-w-none')}
            {modeSwitch('min-w-0')}
            <button data-testid="chat-new-session-compact" onClick={newSession} disabled={thinking || modelLoading || !userId} className="chat-icon-action" title="新建对话" aria-label="新建对话"><Plus size={17} /></button>
            <button data-testid="floating-chat-delete" onClick={deleteSession} disabled={thinking || modelLoading || !userId || !currentSessionId} className="chat-icon-action text-rose-500 hover:text-rose-600" title="删除当前对话" aria-label="删除当前对话"><Trash2 size={16} /></button>
          </div>
        </>
      ) : (
        <>
          <div className="min-w-0 flex-1 lg:max-w-[15rem]">
            <div className="flex min-w-0 items-center gap-2"><h1 className="truncate text-sm font-bold text-slate-950 dark:text-slate-50">{title}</h1><RealtimeSyncIndicator state={realtimeSyncState} /></div>
            <p className="mt-0.5 text-[11px] font-medium text-slate-400">{messagesLength} 条消息</p>
          </div>
          {visibleSessions.length > 0 && (
            <select value={currentSessionId} onChange={(event) => switchSession(event.target.value)} disabled={thinking || modelLoading} className="chat-compact-select max-w-40 lg:hidden">
              {visibleSessions.map((session) => <option key={session.session_id} value={session.session_id}>{session.title || '新对话'}</option>)}
            </select>
          )}
          <button data-testid="chat-new-session-compact" onClick={newSession} disabled={thinking || modelLoading || !userId} className="chat-icon-action lg:hidden" title="新建对话"><Plus size={17} /></button>
          {modelSelector('chat-model-select')}
          <button data-testid="chat-upload-button" onClick={() => fileInputRef.current?.click()} disabled={uploading || !userId} className="chat-secondary-action hidden sm:inline-flex">
            <UploadCloud size={15} strokeWidth={1.8} /> {uploading ? '上传中...' : '上传数据'}
          </button>
          {modeSwitch()}
          <button onClick={runThesisWorkflow} disabled={thinking || !userId} className="chat-icon-action" title="运行论文流程">
            <PlayCircle size={17} strokeWidth={1.7} />
          </button>
        </>
      )}
      <input
        ref={fileInputRef}
        data-testid="chat-file-input"
        type="file"
        multiple
        className="hidden"
        accept=".zip,.shp,.shx,.dbf,.prj,.cpg,.geojson,.gpkg,.kml,.csv,.xlsx,.xls,.tif,.tiff,.img,.docx,.txt,.md"
        onChange={(event) => uploadFiles(event.target.files)}
      />
    </header>
  );
}
