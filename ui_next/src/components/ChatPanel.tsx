import { useCallback, useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Map as MapIcon, SearchCheck, Sparkles, UploadCloud, X } from 'lucide-react';
import { api, ChatMessage, ChatSession, CommercialUser, RealtimeChatEvent, ResultPanel, WorkspaceMention } from '@/lib/api';
import { GlassCard } from './GlassCard';
import { cn } from '@/lib/cn';
import type { ParsedMapTextCommand } from './mapTextCommands';
import { assistantReplyContent, normalizeChatMessages } from './chatMessageContent';
import type { ChatContextPayload } from '@/lib/chatContext';
import { GSCloudAccountPanel } from './GSCloudAccountPanel';
import { ModalPortal } from './ModalPortal';
import { TaskSummaryRail } from './chat/TaskSummaryRail';
import { ChatConversationHeader } from './chat/ChatConversationHeader';
import { ChatSessionSidebar } from './chat/ChatSessionSidebar';
import { ChatMessageList } from './chat/ChatMessageList';
import { ChatComposerFooter } from './chat/ChatComposerFooter';
import { mergeRealtimeEventMeta, shouldUseRealtimeEventContent } from './chat/chatRealtimeEventModel';
import { hashString, messageIsToolTask, messageKey } from './chat/chatWorkspaceModel';
import { useChatStreamLifecycle } from './chat/useChatStreamLifecycle';
import { useChatModels } from './chat/useChatModels';
import { useChatSessions } from './chat/useChatSessions';
import { useChatTaskWorkbench } from './chat/useChatTaskWorkbench';
import { useChatRealtimeEvents } from './chat/useChatRealtimeEvents';
import { useChatDownloads } from './chat/useChatDownloads';
import { useChatWorkspaceMentions } from './chat/useChatWorkspaceMentions';
import { useChatUploads } from './chat/useChatUploads';
import { useChatVoiceInput } from './chat/useChatVoiceInput';
import { useChatPanelResize } from './chat/useChatPanelResize';
import { useChatAutoScroll } from './chat/useChatAutoScroll';
import { useChatExternalPrompt } from './chat/useChatExternalPrompt';
import { useChatEditing } from './chat/useChatEditing';
import { useChatThesisWorkflow } from './chat/useChatThesisWorkflow';
import { useChatInteractionModeAction } from './chat/useChatInteractionModeAction';
import { useChatNewSessionAction } from './chat/useChatNewSessionAction';
import { useChatSwitchSessionAction } from './chat/useChatSwitchSessionAction';
import { useChatDeleteSessionAction } from './chat/useChatDeleteSessionAction';
import { useChatMapCommandAction } from './chat/useChatMapCommandAction';
import { useChatPromptPreparation } from './chat/useChatPromptPreparation';
import { useChatPromptStreamAction } from './chat/useChatPromptStreamAction';
import { useChatConfirmationAction } from './chat/useChatConfirmationAction';

export type ExternalPromptCommand = { id: number; prompt: string };
type ChatWorkspaceMode = 'floating' | 'page';
export type ChatWorkspaceProps = {
  user: CommercialUser | null;
  setUser: (u: CommercialUser | null) => void;
  onClose?: () => void;
  onMapTextCommand?: (command: ParsedMapTextCommand) => string;
  externalPrompt?: ExternalPromptCommand | null;
  onResultPanel?: (panel: ResultPanel) => void;
  onSessionChange?: (sessionId: string) => void;
  chatContext?: ChatContextPayload;
  mentionDatasets?: Array<Record<string, unknown> | WorkspaceMention>;
  mode?: ChatWorkspaceMode;
};

const EMPTY_MENTION_DATASETS: Array<Record<string, unknown> | WorkspaceMention> = [];

const PROMPT_GROUPS = [
  {
    title: '检查工作区数据',
    description: '识别字段、坐标、时间与缺失值',
    icon: SearchCheck,
    prompt: '检查当前上传数据的字段、坐标、时间和缺失值，给出下一步处理计划。'
  },
  {
    title: '开始融合建模',
    description: '按论文流程准备模型与验证',
    icon: Sparkles,
    prompt: '按照闪电河流域土壤水分融合论文流程，检查能否做 BTCH、RF、XGBoost、LSTM 与 GCP。'
  },
  {
    title: '创建地图',
    description: '从现有图层生成制图方案',
    icon: MapIcon,
    prompt: '概括当前工作区数据，并判断哪些数据可直接用于制图、建模或结果分析。'
  },
  {
    title: '准备下载数据',
    description: '查找 DEM、遥感或土壤水分数据',
    icon: UploadCloud,
    prompt: '根据当前工作区数据，检查是否可以下载 DEM、Sentinel-2 或土壤水分相关数据。'
  }
];

function renderInlineMarkdown(text: string) {
  let offset = 0;
  return String(text || '').split(/(\*\*\*[^*]+\*\*\*|\*\*[^*]+\*\*)/g).map((part) => {
    const bold = part.match(/^\*{2,3}(.+)\*{2,3}$/);
    const key = `inline-${offset}-${hashString(part)}`;
    offset += part.length;
    return bold ? <strong key={key} className="font-black text-inherit">{bold[1]}</strong> : <span key={key}>{part}</span>;
  });
}

function responseAssistantMessage(response: {
  reply?: string;
  model?: string;
  reason?: string;
  artifacts?: unknown;
  files?: unknown;
  presentation_result?: unknown;
  execution_summary?: unknown;
  user_facing_result?: unknown;
  management_view?: unknown;
  download_management_view?: unknown;
  task_card?: unknown;
  confirmed_pending_confirmation_id?: unknown;
  [key: string]: unknown;
}): ChatMessage {
  const meta: Record<string, unknown> = {
    model: response.model,
    reason: response.reason,
    artifacts: response.artifacts || response.files || [],
    presentation_result: response.presentation_result,
    execution_summary: response.execution_summary,
    user_facing_result: response.user_facing_result,
  };
  ['management_view', 'download_management_view', 'task_card', 'confirmed_pending_confirmation_id', 'interaction_type', 'mode', 'status'].forEach((key) => {
    if (response[key] !== undefined) meta[key] = response[key];
  });
  return { role: 'assistant', content: assistantReplyContent(response.reply), meta };
}

function messageMatchesConfirmation(message: ChatMessage, confirmationId: string) {
  const token = confirmationId.trim();
  if (!token || message.role !== 'assistant') return false;
  const meta = message.meta || {};
  const action = (meta.action_required || {}) as Record<string, unknown>;
  return String(action.confirmed_action_id || '') === token
    || String(meta.confirmed_pending_confirmation_id || '') === token
    || String(meta.confirmation_id || '') === token;
}

function taskIdsFromMessage(message: ChatMessage) {
  const meta = message.meta || {};
  const action = (meta.action_required || {}) as Record<string, unknown>;
  const managementView = (meta.management_view || meta.download_management_view || {}) as Record<string, unknown>;
  const card = (meta.task_card || {}) as Record<string, unknown>;
  return new Set(
    [
      action.job_id,
      managementView.task_id,
      managementView.job_id,
      card.task_id,
      meta.job_id,
      meta.task_id,
    ]
      .map((value) => String(value || '').trim())
      .filter(Boolean)
  );
}

function messageMatchesJob(message: ChatMessage, jobId: string) {
  const target = jobId.trim();
  if (!target || message.role !== 'assistant') return false;
  return taskIdsFromMessage(message).has(target);
}

function messageMatchesRealtimeEvent(message: ChatMessage, event: RealtimeChatEvent) {
  if (message.role !== 'assistant') return false;
  const taskId = String(event.task_id || '').trim();
  const jobId = String(event.job_id || '').trim();
  const ids = taskIdsFromMessage(message);
  return Boolean((taskId && ids.has(taskId)) || (jobId && ids.has(jobId)));
}

function mergeTaskCardUpdate(
  current: ChatMessage[],
  matcher: (message: ChatMessage) => boolean,
  update: ChatMessage,
  options: { consumeAction?: boolean } = {}
) {
  let matched = false;
  const next = [...current];
  for (let index = next.length - 1; index >= 0; index -= 1) {
    const existing = next[index];
    if (!matcher(existing)) continue;
    matched = true;
    const mergedMeta = { ...(existing.meta || {}), ...(update.meta || {}) } as NonNullable<ChatMessage['meta']>;
    if (options.consumeAction) delete mergedMeta.action_required;
    next[index] = {
      ...existing,
      content: update.content || existing.content,
      meta: mergedMeta,
    };
    break;
  }
  return matched ? next : [...current, update];
}

function messageSignature(message: ChatMessage) {
  return `${message.role}|${String(message.content || '')}`;
}

function mergeStableClientMessageIds(current: ChatMessage[], incoming: ChatMessage[]) {
  const clientIds = new Map<string, string[]>();
  current.forEach((message) => {
    if (!message.id) return;
    const signature = messageSignature(message);
    const bucket = clientIds.get(signature) || [];
    bucket.push(message.id);
    clientIds.set(signature, bucket);
  });
  return incoming.map((message) => {
    if (message.id) return message;
    const bucket = clientIds.get(messageSignature(message));
    const id = bucket?.shift();
    return id ? { ...message, id } : message;
  });
}

function mergeServerMessages(current: ChatMessage[], incoming: ChatMessage[]) {
  if (!incoming.length && current.length > 0) return current;
  return mergeStableClientMessageIds(current, incoming);
}

function MarkdownMessage({ content }: { content: string }) {
  const lines = String(content || '').split(/\r?\n/);
  let offset = 0;
  return (
    <div className="chat-markdown">
      {lines.map((line) => {
        const key = `line-${offset}-${hashString(line)}`;
        offset += line.length + 1;
        const trimmed = line.trim();
        if (!trimmed) return <div key={key} className="h-2" />;
        const heading = trimmed.match(/^#{1,6}\s+(.+)$/);
        if (heading) return <div key={key} className="chat-md-heading">{renderInlineMarkdown(heading[1])}</div>;
        if (/^\*{3,}$/.test(trimmed) || /^-{3,}$/.test(trimmed)) return <div key={key} className="chat-md-rule" />;
        const bullet = trimmed.match(/^[-*]\s+(.+)$/);
        if (bullet) return <div key={key} className="chat-md-list"><span>•</span><span>{renderInlineMarkdown(bullet[1])}</span></div>;
        const numbered = trimmed.match(/^(\d+)[.)]\s+(.+)$/);
        if (numbered) return <div key={key} className="chat-md-list"><span>{numbered[1]}.</span><span>{renderInlineMarkdown(numbered[2])}</span></div>;
        return <div key={key}>{renderInlineMarkdown(line)}</div>;
      })}
    </div>
  );
}

export function ChatWorkspace({
  user,
  onClose,
  onMapTextCommand,
  externalPrompt,
  onResultPanel,
  onSessionChange,
  chatContext = {},
  mentionDatasets = EMPTY_MENTION_DATASETS,
  mode = 'floating'
}: ChatWorkspaceProps) {
  const userId = user?.user_id || '';
  const streamLifecycle = useChatStreamLifecycle({ userId });
  const { thinking } = streamLifecycle;
  const { panelRef, panelStyle, dragHandle } = useChatPanelResize();
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [error, setError] = useState('');
  const [lastFailedPrompt, setLastFailedPrompt] = useState('');
  const { renderMessages, taskSummaryItems } = useChatTaskWorkbench(messages);
  const { listRef, handleScroll } = useChatAutoScroll({ messages, thinking });
  const fileInputRef = useRef<HTMLInputElement>(null);
  const mountedRef = useRef(true);
  const handleSessionMessagesRefreshed = useCallback((incoming: ChatMessage[]) => {
    setMessages((current) => mergeServerMessages(current, normalizeChatMessages(incoming)));
  }, []);
  const handleSessionMessagesCleared = useCallback(() => setMessages([]), []);
  const handleSessionRefreshError = useCallback(() => {
    setError('聊天记录加载失败，已保留当前显示内容，可稍后重试。');
    setMessages((current) => current.length ? [...current, { role: 'system', content: '聊天记录暂时无法刷新，已保留当前显示内容。', meta: { reason: 'chat_load_failed' } }] : current);
  }, []);
  const {
    sessions,
    setSessions,
    currentSessionId,
    setCurrentSessionId,
    visibleSessions,
    currentSession,
    refreshSessions,
  } = useChatSessions({
    userId,
    onSessionChange,
    onMessagesCleared: handleSessionMessagesCleared,
    onMessagesRefreshed: handleSessionMessagesRefreshed,
    onRefreshError: handleSessionRefreshError,
  });
  const { workspaceMentions, setWorkspaceMentions } = useChatWorkspaceMentions({
    mentionDatasets,
    userId,
    sessionId: currentSessionId,
  });
  const currentInteractionMode = currentSession?.interaction_mode === 'tool_enabled' ? 'tool_enabled' : 'chat_only';
  const interactionModeLabel = currentInteractionMode === 'tool_enabled'
    ? '工具模式：可以在确认和校验后执行下载、GIS 处理和建模。'
    : '聊天模式：只回答问题，不会操作数据或创建任务。';
  const {
    chatModels,
    visibleModels,
    modelLoading,
    modelNotice,
    modelError,
    changeChatModel,
  } = useChatModels({ userId, sessionId: currentSessionId });
  const handleInteractionModeChanged = useCallback((response: Awaited<ReturnType<typeof api.setChatInteractionMode>>) => {
    setSessions(response.sessions || []);
    if (response.current_session_id) setCurrentSessionId(response.current_session_id);
    if (response.messages) setMessages((current) => mergeServerMessages(current, normalizeChatMessages(response.messages)));
  }, [setCurrentSessionId, setSessions]);
  const { setInteractionMode } = useChatInteractionModeAction({
    thinking,
    userId,
    currentSessionId,
    currentInteractionMode,
    setError,
    onModeChanged: handleInteractionModeChanged,
  });
  const handleSessionCreated = useCallback((response: Awaited<ReturnType<typeof api.createChatSession>>) => {
    setSessions(response.sessions || []);
    const nextSessionId = response.current_session_id || response.session_id;
    setCurrentSessionId(nextSessionId);
    onSessionChange?.(nextSessionId);
    setMessages(normalizeChatMessages(response.messages));
    setInput('');
  }, [onSessionChange, setCurrentSessionId, setSessions]);
  const { newSession } = useChatNewSessionAction({
    thinking,
    userId,
    setError,
    onSessionCreated: handleSessionCreated,
  });
  const handleEditedRetryComplete = useCallback((response: Awaited<ReturnType<typeof api.retryMessage>>) => {
    setMessages((current) => mergeServerMessages(current, normalizeChatMessages(response.messages)));
    setSessions(response.sessions || []);
    const nextSessionId = response.current_session_id || currentSessionId;
    setCurrentSessionId(nextSessionId);
    onSessionChange?.(nextSessionId);
  }, [currentSessionId, onSessionChange, setCurrentSessionId, setSessions]);
  const {
    editingId,
    editText,
    setEditText,
    beginEdit,
    cancelEdit,
    retryEditedMessage,
  } = useChatEditing({
    thinking,
    userId,
    currentSessionId,
    streamLifecycle,
    setError,
    onRetryComplete: handleEditedRetryComplete,
  });
  const handleSessionSwitched = useCallback((sessionId: string, response: Awaited<ReturnType<typeof api.switchChatSession>>) => {
    setSessions(response.sessions || []);
    const nextSessionId = response.current_session_id || sessionId;
    setCurrentSessionId(nextSessionId);
    onSessionChange?.(nextSessionId);
    setMessages(normalizeChatMessages(response.messages));
    cancelEdit();
  }, [cancelEdit, onSessionChange, setCurrentSessionId, setSessions]);
  const { switchSession } = useChatSwitchSessionAction({
    thinking,
    modelLoading,
    userId,
    currentSessionId,
    setError,
    onSessionSwitched: handleSessionSwitched,
  });
  const handleSessionDeleted = useCallback((response: Awaited<ReturnType<typeof api.deleteChatSession>> | Awaited<ReturnType<typeof api.clearChatSession>>) => {
    setSessions(response.sessions || []);
    const nextSessionId = response.current_session_id || '';
    setCurrentSessionId(nextSessionId);
    onSessionChange?.(nextSessionId);
    setMessages(normalizeChatMessages(response.messages));
    cancelEdit();
  }, [cancelEdit, onSessionChange, setCurrentSessionId, setSessions]);
  const { deleteSession } = useChatDeleteSessionAction({
    thinking,
    userId,
    currentSessionId,
    sessionCount: sessions.length,
    setError,
    onSessionDeleted: handleSessionDeleted,
  });
  const handleWorkflowComplete = useCallback((response: Awaited<ReturnType<typeof api.runSoilMoistureWorkflow>>) => {
    if (response.sessions) setSessions(response.sessions);
    if (response.result_panel) onResultPanel?.(response.result_panel);
    const nextSessionId = response.current_session_id || currentSessionId;
    setCurrentSessionId(nextSessionId);
    onSessionChange?.(nextSessionId);
  }, [currentSessionId, onResultPanel, onSessionChange, setCurrentSessionId, setSessions]);
  const { runThesisWorkflow } = useChatThesisWorkflow({
    thinking,
    userId,
    currentSessionId,
    streamLifecycle,
    setError,
    setMessages,
    setLastFailedPrompt,
    onWorkflowComplete: handleWorkflowComplete,
  });

  const mergeRealtimeEvent = useCallback((event: RealtimeChatEvent, syncState: 'connecting' | 'live' | 'polling') => {
    const taskUpdate = event.task_update && typeof event.task_update === 'object' ? event.task_update : {};
    const meta: Record<string, unknown> = {
      task_id: event.task_id || '',
      job_id: event.job_id || '',
      status: event.status || '',
      progress: event.progress,
      phase: event.phase,
      current_step: event.current_step,
      heartbeat_at: event.heartbeat_at,
      started_at: event.started_at,
      elapsed_ms: event.elapsed_ms,
      timeout_reason: event.timeout_reason,
      realtime_sync: syncState,
      streaming: event.kind === 'model_token',
      ...taskUpdate,
    };
    if (event.management_view) meta.management_view = event.management_view;
    if (event.presentation_result) meta.presentation_result = event.presentation_result;
    const content = event.kind === 'model_token'
      ? event.delta || ''
      : event.kind === 'model_complete'
        ? event.delta || ''
        : event.message || '';
    setMessages((current) => {
      const next = [...current];
      for (let index = next.length - 1; index >= 0; index -= 1) {
        const existing = next[index];
        if (!messageMatchesRealtimeEvent(existing, event)) continue;
        const mergedMeta = mergeRealtimeEventMeta(existing.meta || {}, meta, event);
        const nextContent = shouldUseRealtimeEventContent(existing.meta || {}, meta, event) ? content : '';
        next[index] = {
          ...existing,
          content: event.kind === 'model_token' ? `${existing.content || ''}${nextContent}` : (nextContent || existing.content),
          meta: { ...mergedMeta, streaming: event.kind === 'model_token' },
        };
        return next;
      }
      return current;
    });
  }, []);

  const { realtimeSyncState, applyRealtimeEvent } = useChatRealtimeEvents({
    userId,
    sessionId: currentSessionId,
    onEvent: mergeRealtimeEvent,
  });

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const { uploading, uploadFiles } = useChatUploads({
    userId,
    sessionId: currentSessionId,
    fileInputRef,
    setError,
    setMessages,
    setWorkspaceMentions,
  });
  const {
    listening,
    voiceSupported,
    voiceUnavailableReason,
    toggleVoice,
  } = useChatVoiceInput({ setInput, setError });

  const {
    gscloudLoginOpen,
    closeGSCloudLogin,
    pendingLoginJobId,
    resumeReadyJobIds,
    openGSCloudLogin,
    markGSCloudLoginComplete,
    resumeDownload,
    cancelDownload,
    retryDownload,
  } = useChatDownloads({
    messages,
    setMessages,
    userId,
    sessionId: currentSessionId,
    mountedRef,
    messageKey,
    messageMatchesJob,
    mergeTaskCardUpdate,
  });
  const { handleMapCommand } = useChatMapCommandAction({
    onMapTextCommand,
    setMessages,
  });
  const { streamPrompt } = useChatPromptStreamAction({
    userId,
    currentSessionId,
    currentInteractionMode,
    chatContext,
    realtimeSyncState,
    streamLifecycle,
    applyRealtimeEvent,
    setMessages,
    setLastFailedPrompt,
    setError,
    refreshSessions,
    messageMatchesJob,
    mergeTaskCardUpdate,
  });
  const { preparePrompt } = useChatPromptPreparation({
    thinking,
    userId,
    setInput,
    setError,
  });
  const handleConfirmationComplete = useCallback((token: string, response: Awaited<ReturnType<typeof api.confirmChatAction>>) => {
    if (response.messages) {
      const incoming = normalizeChatMessages(response.messages);
      const updated = incoming.find((message) => message.role === 'assistant' && messageMatchesConfirmation(message, token))
        || [...incoming].reverse().find((message) => message.role === 'assistant' && messageIsToolTask(message));
      setMessages((current) => updated
        ? mergeTaskCardUpdate(current, (message) => messageMatchesConfirmation(message, token), updated, { consumeAction: true })
        : mergeServerMessages(current, incoming));
    } else {
      setMessages((current) => mergeTaskCardUpdate(current, (message) => messageMatchesConfirmation(message, token), responseAssistantMessage(response), { consumeAction: true }));
    }
    if (response.sessions) setSessions(response.sessions);
    if (response.result_panel) onResultPanel?.(response.result_panel);
    const nextSessionId = response.current_session_id || currentSessionId;
    setCurrentSessionId(nextSessionId);
    onSessionChange?.(nextSessionId);
    setLastFailedPrompt('');
    refreshSessions().catch(() => {});
  }, [currentSessionId, onResultPanel, onSessionChange, refreshSessions, setCurrentSessionId, setSessions]);
  const { confirmAction } = useChatConfirmationAction({
    thinking,
    userId,
    currentSessionId,
    chatContext,
    streamLifecycle,
    setError,
    setMessages,
    onConfirmationComplete: handleConfirmationComplete,
  });

  const chooseClarification = (value: string, label: string) => {
    if (value === 'upload_boundary') {
      fileInputRef.current?.click();
      return;
    }
    if (value === 'active_region') {
      sendPrompt('帮我下载当前研究区的 DEM，使用默认 30m GeoTIFF 并裁剪到研究区。');
      return;
    }
    setInput(value === 'admin_region' ? '下载行政区：' : '下载 bbox：');
    setError(`请补充${label}后发送。`);
  };

  const appendSystem = (content: string) => setMessages((v) => [...v, { role: 'system', content }]);

  const sendPrompt = async (prompt: string) => {
    const text = preparePrompt(prompt);
    if (!text) return;
    if (handleMapCommand(text)) return;
    await streamPrompt(text);
  };

  const send = () => sendPrompt(input);

  useChatExternalPrompt({ externalPrompt, sendPrompt });

  const isPage = mode === 'page';
  const workspaceBody = (
    <>
        <ChatConversationHeader
          isPage={isPage}
          currentSession={currentSession}
          currentSessionId={currentSessionId}
          visibleSessions={visibleSessions}
          messagesLength={messages.length}
          realtimeSyncState={realtimeSyncState}
          onClose={onClose}
          switchSession={switchSession}
          newSession={newSession}
          deleteSession={deleteSession}
          runThesisWorkflow={runThesisWorkflow}
          chatModels={chatModels}
          visibleModels={visibleModels}
          modelLoading={modelLoading}
          modelNotice={modelNotice}
          modelError={modelError}
          thinking={thinking}
          userId={userId}
          changeChatModel={changeChatModel}
          uploading={uploading}
          fileInputRef={fileInputRef}
          uploadFiles={uploadFiles}
          currentInteractionMode={currentInteractionMode}
          setInteractionMode={setInteractionMode}
          interactionModeLabel={interactionModeLabel}
        />

        {isPage && (
          <ChatSessionSidebar
            currentSessionId={currentSessionId}
            visibleSessions={visibleSessions}
            messagesLength={messages.length}
            thinking={thinking}
            modelLoading={modelLoading}
            userId={userId}
            switchSession={switchSession}
            newSession={newSession}
            deleteSession={deleteSession}
          />
        )}

        {isPage && (
          <TaskSummaryRail
            taskSummaryItems={taskSummaryItems}
            realtimeState={realtimeSyncState}
            messageCount={messages.length}
          />
        )}

        <ChatMessageList
          isPage={isPage}
          listRef={listRef}
          messages={messages}
          renderMessages={renderMessages}
          promptGroups={PROMPT_GROUPS}
          sendPrompt={sendPrompt}
          editingId={editingId}
          editText={editText}
          setEditText={setEditText}
          cancelEdit={cancelEdit}
          retryEditedMessage={retryEditedMessage}
          beginEdit={beginEdit}
          resumeReadyJobIds={resumeReadyJobIds}
          openGSCloudLogin={openGSCloudLogin}
          resumeDownload={resumeDownload}
          cancelDownload={cancelDownload}
          retryDownload={retryDownload}
          chooseClarification={chooseClarification}
          confirmAction={confirmAction}
          currentSessionId={currentSessionId}
          lastFailedPrompt={lastFailedPrompt}
          thinking={thinking}
          currentInteractionMode={currentInteractionMode}
          error={error}
          onScroll={handleScroll}
        />

        <ChatComposerFooter
          isPage={isPage}
          thinking={thinking}
          userId={userId}
          input={input}
          setInput={setInput}
          send={send}
          uploadFiles={uploadFiles}
          stopCurrentRequest={streamLifecycle.stopCurrentRequest}
          uploading={uploading}
          voiceSupported={voiceSupported}
          listening={listening}
          voiceUnavailableReason={voiceUnavailableReason}
          toggleVoice={toggleVoice}
          workspaceMentions={workspaceMentions}
        />
        {!isPage && <div {...dragHandle} className="absolute right-0 top-0 h-full w-2 cursor-ew-resize" />}
        <ModalPortal>
          <AnimatePresence>
            {gscloudLoginOpen && (
              <motion.div className="fixed inset-0 z-[95] grid place-items-end bg-slate-950/30 p-3 backdrop-blur-sm sm:place-items-center" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                <motion.div data-testid="gscloud-login-dialog" className="max-h-[calc(100dvh-1.5rem)] w-full max-w-md overflow-y-auto rounded-[24px] border border-white/35 bg-white p-4 shadow-2xl dark:border-white/10 dark:bg-slate-900" initial={{ y: 18, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 18, opacity: 0 }}>
                  <div className="mb-3 flex items-center justify-between">
                    <div><div className="font-black">登录数据源账号</div><p className="text-xs text-slate-500">登录成功后可继续当前下载任务</p></div>
                    <button type="button" onClick={closeGSCloudLogin} className="chat-icon-action" aria-label="关闭登录引导"><X size={17} /></button>
                  </div>
                  <GSCloudAccountPanel enabled={Boolean(userId)} pendingJobId={pendingLoginJobId} onLoginComplete={markGSCloudLoginComplete} />
                </motion.div>
              </motion.div>
            )}
          </AnimatePresence>
        </ModalPortal>
    </>
  );

  if (isPage) {
    return (
      <section
        data-testid="chat-page-workspace"
        className="relative flex h-full min-h-0 w-full flex-col overflow-hidden rounded-none border-0 bg-white/90 shadow-none backdrop-blur dark:bg-slate-900/86 lg:grid lg:h-full lg:min-h-0 lg:grid-cols-[190px_minmax(0,1fr)_340px] lg:grid-rows-[auto_minmax(0,1fr)_auto]"
      >
        {workspaceBody}
      </section>
    );
  }

  return (
    <motion.aside
      ref={panelRef}
      style={panelStyle}
      initial={{ opacity: 0, x: -16 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ type: 'spring', stiffness: 300, damping: 30 }}
      exit={{ opacity: 0, x: -24, scale: 0.98 }}
      className="no-drag fixed bottom-4 left-3 top-8 z-30 flex max-w-[680px] flex-col rounded-[28px] sm:left-4"
    >
      <GlassCard className="relative flex h-full flex-col overflow-hidden p-0">
        {workspaceBody}
      </GlassCard>
    </motion.aside>
  );
}

export function ChatPanel(props: Omit<ChatWorkspaceProps, 'mode'>) {
  return <ChatWorkspace {...props} mode="floating" />;
}
