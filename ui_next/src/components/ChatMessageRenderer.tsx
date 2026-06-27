import { Check, Clipboard, Copy, LogIn, Package, Play, ShieldCheck, XCircle } from 'lucide-react';
import { isValidElement, useEffect, useState, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeSanitize from 'rehype-sanitize';
import remarkGfm from 'remark-gfm';
import { type ChatArtifact, type ChatMessage, type PresentationResult, type UserFacingResult } from '@/lib/api';
import { cn } from '@/lib/cn';
import { ArtifactDownloadCard } from './ArtifactDownloadCard';
import { TaskStatusCard, ResultGroups, artifactKey, stableTextKey, statusLabel, technicalDetailsEnabled } from './chat/task-card';

function useCopyToast() {
  const [copied, setCopied] = useState(false);
  const copyText = async (text: string) => {
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2400);
    try {
      await navigator.clipboard.writeText(String(text || ''));
    } catch {
      const target = document.createElement('textarea');
      target.value = String(text || '');
      target.setAttribute('readonly', 'true');
      target.style.position = 'fixed';
      target.style.left = '-9999px';
      document.body.appendChild(target);
      target.select();
      document.execCommand('copy');
      target.remove();
    }
  };
  return { copied, copyText };
}

function CopyButton({ text, label, testId }: { text: string; label: string; testId?: string }) {
  const { copied, copyText } = useCopyToast();
  return (
    <button
      data-testid={testId}
      type="button"
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        copyText(text);
      }}
      className={cn('chat-copy-button', copied && 'is-copied')}
      title={copied ? '已复制' : label}
    >
      {copied ? <Check size={13} /> : <Copy size={13} />}
      <span>{copied ? '已复制' : label}</span>
    </button>
  );
}

const MARKDOWN_COMPONENTS = {
  code({ inline, className, children, node: _node, ...props }: any) {
    if (inline) {
      return <code className="chat-inline-code" {...props}>{children}</code>;
    }
    return <code className={className} {...props}>{children}</code>;
  },
  pre({ children }: { children?: ReactNode }) {
    const child = Array.isArray(children) ? children[0] : children;
    const codeProps = isValidElement(child)
      ? child.props as { className?: string; children?: ReactNode }
      : {};
    const value = String(codeProps.children || '').replace(/\n$/, '');
    const lang = /language-([\w-]+)/.exec(codeProps.className || '')?.[1] || '代码';
    return (
      <div className="chat-code-block">
        <div className="chat-code-toolbar">
          <span>{lang}</span>
          <CopyButton text={value} label="复制代码" testId="copy-code" />
        </div>
        <pre>{children}</pre>
      </div>
    );
  },
  table({ children }: { children?: ReactNode }) {
    return <div className="chat-table-wrap"><table>{children}</table></div>;
  },
};

function MarkdownBlocks({ content }: { content: string }) {
  return (
    <div className="chat-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize]}
        components={MARKDOWN_COMPONENTS}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function artifactsFromMessage(message: ChatMessage): ChatArtifact[] {
  const seen = new Set<string>();
  return (message.meta?.artifacts || []).filter((item): item is ChatArtifact => {
    if (!item?.artifact_id || seen.has(item.artifact_id)) return false;
    seen.add(item.artifact_id);
    return true;
  });
}

function userFacingResultFromMessage(message: ChatMessage): UserFacingResult | null {
  const result = message.meta?.user_facing_result;
  return result && typeof result === 'object' ? result : null;
}

function presentationResultFromMessage(message: ChatMessage): PresentationResult | null {
  const result = message.meta?.presentation_result;
  return result && typeof result === 'object' ? result : null;
}

function UserFacingResultCard({
  result,
  sessionId,
  onDeleted
}: {
  result: UserFacingResult;
  sessionId?: string;
  onDeleted?: (artifactId: string) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const primary = (result.primary_artifacts || []).filter((item) => item?.artifact_id);
  const previews = (result.preview_artifacts || []).filter((item) => item?.artifact_id);
  const primaryIds = new Set(primary.map((item) => item.artifact_id));
  const previewOnly = previews.filter((item) => !primaryIds.has(item.artifact_id));
  const groups = result.grouped_artifacts || [];
  const bundles = [result.download_bundle?.recommended, result.download_bundle?.all].filter((item): item is ChatArtifact => Boolean(item?.artifact_id));
  const debug = { ...(result.technical_details || {}), ...(result.debug || {}) };
  const showTechnicalDetails = technicalDetailsEnabled();

  return (
    <section data-testid="user-facing-result-card" className="mt-3 space-y-3 rounded-2xl border border-slate-200/85 bg-white/70 p-3 shadow-sm dark:border-slate-800 dark:bg-slate-950/35">
      {result.summary && <div className="text-sm font-bold leading-6 text-slate-800 dark:text-slate-100">{result.summary}</div>}
      {Boolean(result.key_findings?.length) && (
        <div className="grid gap-2 sm:grid-cols-2">
          {result.key_findings?.slice(0, 6).map((item, index) => (
            <div key={`${item}-${index}`} className="rounded-xl bg-slate-50 px-3 py-2 text-xs font-bold text-slate-700 dark:bg-slate-900 dark:text-slate-200">{item}</div>
          ))}
        </div>
      )}
      {Boolean(result.insights?.length) && (
        <div className="space-y-1 text-xs leading-5 text-slate-600 dark:text-slate-300">
          {result.insights?.slice(0, 5).map((item, index) => <div key={`${item}-${index}`}>• {item}</div>)}
        </div>
      )}
      {Boolean(result.warnings?.length) && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
          {result.warnings?.slice(0, 4).map((item, index) => <div key={`${item}-${index}`}>• {item}</div>)}
        </div>
      )}
      {bundles.length > 0 && (
        <div data-testid="download-bundle-actions" className="grid gap-2">
          {bundles.map((artifact) => (
            <ArtifactDownloadCard key={artifactKey(artifact)} artifact={artifact} sessionId={sessionId} onDeleted={onDeleted} />
          ))}
        </div>
      )}
      {(primary.length > 0 || previewOnly.length > 0) && (
        <div className="artifact-download-list">
          {[...primary, ...previewOnly].map((artifact) => (
            <ArtifactDownloadCard key={artifactKey(artifact)} artifact={artifact} sessionId={sessionId} onDeleted={onDeleted} />
          ))}
        </div>
      )}
      {showAll && groups.length > 0 && (
        <div data-testid="artifact-group-list" className="space-y-3">
          {groups.map((group) => (
            <div key={group.group} className="space-y-2">
              <div className="flex items-center gap-2 text-xs font-black text-slate-500 dark:text-slate-400"><Package size={13} />{group.group}</div>
              {(group.artifacts || []).filter((item) => item?.artifact_id).map((artifact) => (
                <ArtifactDownloadCard key={artifactKey(artifact)} artifact={artifact} sessionId={sessionId} onDeleted={onDeleted} />
              ))}
            </div>
          ))}
        </div>
      )}
      {groups.length > 0 && (
        <button type="button" onClick={() => setShowAll((value) => !value)} className="chat-copy-button">
          {showAll ? '收起文件' : '展开全部文件'}
        </button>
      )}
      {Boolean(result.next_actions?.length) && (
        <div className="space-y-1 text-xs leading-5 text-slate-600 dark:text-slate-300">
          {result.next_actions?.slice(0, 5).map((item, index) => <div key={`${item}-${index}`}>下一步：{item}</div>)}
        </div>
      )}
      {showTechnicalDetails && Object.keys(debug).length > 0 && (
        <details data-testid="technical-details" className="rounded-xl border border-slate-200 bg-slate-50 p-2 text-xs dark:border-slate-800 dark:bg-slate-900/60">
          <summary className="cursor-pointer font-bold text-slate-600 dark:text-slate-300">查看技术详情</summary>
          <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap text-[11px] leading-5 text-slate-500 dark:text-slate-400">{JSON.stringify(debug, null, 2)}</pre>
        </details>
      )}
    </section>
  );
}

function PresentationResultCard({
  result,
  sessionId,
  onDeleted,
}: {
  result: PresentationResult;
  sessionId?: string;
  onDeleted?: (artifactId: string) => void;
}) {
  const status = String(result.status || '');
  return (
    <section data-testid="presentation-result-card" className="mt-3 space-y-3 rounded-2xl border border-slate-200/85 bg-white/75 p-3 shadow-sm dark:border-slate-800 dark:bg-slate-950/35">
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn(
          'rounded-full px-2 py-0.5 text-[10px] font-black uppercase tracking-wide',
          status === 'succeeded' && 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/35 dark:text-emerald-200',
          status === 'failed' && 'bg-rose-50 text-rose-700 dark:bg-rose-950/35 dark:text-rose-200',
          status === 'blocked' && 'bg-amber-50 text-amber-700 dark:bg-amber-950/35 dark:text-amber-200',
          status === 'awaiting_confirmation' && 'bg-blue-50 text-blue-700 dark:bg-blue-950/35 dark:text-blue-200',
          status === 'running' && 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200',
        )}>{statusLabel(status)}</span>
        {result.schema_version && <span className="text-[11px] font-semibold text-slate-400">{result.schema_version}</span>}
      </div>
      {result.concise_summary && <div className="text-sm font-bold leading-6 text-slate-800 dark:text-slate-100">{result.concise_summary}</div>}
      {Boolean(result.executed_steps?.length) && (
        <div className="grid gap-2 sm:grid-cols-2">
          {result.executed_steps?.slice(0, 6).map((step, index) => (
            <div key={`${step.step_id || index}-${step.tool_name || ''}`} className="rounded-xl bg-slate-50 px-3 py-2 text-xs font-bold text-slate-700 dark:bg-slate-900 dark:text-slate-200">
              <div>{step.step_id || step.tool_name || `步骤 ${index + 1}`}</div>
              <div className="mt-0.5 text-[11px] font-semibold text-slate-500">{step.tool_name || '工具'} · {step.status ? statusLabel(step.status) : '未知状态'}</div>
            </div>
          ))}
        </div>
      )}
      {Boolean(result.result_highlights?.length) && (
        <div className="grid gap-2 sm:grid-cols-2">
          {result.result_highlights?.slice(0, 8).map((item, index) => (
            <div key={`${item}-${index}`} className="rounded-xl bg-emerald-50 px-3 py-2 text-xs font-bold text-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-200">{item}</div>
          ))}
        </div>
      )}
      <ResultGroups result={result} sessionId={sessionId} onDeleted={onDeleted} />
      {Boolean(result.warnings?.length) && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
          {result.warnings?.slice(0, 4).map((item, index) => <div key={`${item}-${index}`}>{item}</div>)}
        </div>
      )}
      {result.error_summary && <div className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs leading-5 text-rose-800 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-200">{result.error_summary}</div>}
      {result.clarification_question && <div className="rounded-xl border border-blue-200 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-800 dark:border-blue-900 dark:bg-blue-950/30 dark:text-blue-200">{result.clarification_question}</div>}
      {Boolean(result.next_action_suggestions?.length) && (
        <div className="space-y-1 text-xs leading-5 text-slate-600 dark:text-slate-300">
          {result.next_action_suggestions?.slice(0, 5).map((item) => <div key={stableTextKey('presentation-next', item)}>下一步：{item}</div>)}
        </div>
      )}
    </section>
  );
}

export function ChatMessageRenderer({
  message,
  content,
  isUser = false,
  isSystem = false,
  resumeReady = false,
  onLogin,
  onResume,
  onCancel,
  onRetry,
  onClarification,
  onConfirmAction,
  sessionId
}: {
  message: ChatMessage;
  content: string;
  isUser?: boolean;
  isSystem?: boolean;
  resumeReady?: boolean;
  onLogin?: (jobId: string) => void;
  onResume?: (jobId: string) => void;
  onCancel?: (jobId: string) => void;
  onRetry?: (jobId: string) => void;
  onClarification?: (value: string, label: string) => void;
  onConfirmAction?: (prompt: string, confirmedActionId: string) => void;
  sessionId?: string;
}) {
  const artifacts = artifactsFromMessage(message);
  const presentationResult = presentationResultFromMessage(message);
  const userResult = userFacingResultFromMessage(message);
  const resultPreference = presentationResult || userResult;
  const [deletedArtifactIds, setDeletedArtifactIds] = useState<Set<string>>(() => new Set());
  const visibleArtifacts = artifacts.filter((artifact) => !deletedArtifactIds.has(artifact.artifact_id));
  const [selection, setSelection] = useState('');
  const { copied, copyText } = useCopyToast();
  const action = message.meta?.action_required;
  const jobId = String(action?.job_id || '');
  const confirmationPrompt = String(action?.confirmation_prompt || '');
  const confirmedActionId = String(action?.confirmed_action_id || '');
  const mode = String(message.meta?.mode || '');
  const reason = String(message.meta?.reason || '');
  const streaming = Boolean(message.meta?.streaming);
  const interactionType = String(message.meta?.interaction_type || '');
  const hasTaskCard = !isUser && !isSystem && reason !== 'tool_mode_required' && (
    interactionType === 'tool_task'
    ||
    Boolean(message.meta?.task_card)
    || Boolean(message.meta?.management_view)
    || Boolean(message.meta?.download_management_view)
    || ['background_worker', 'validated_download_executor', 'coordinated_workflow', 'validated_workflow_executor', 'validated_tool_executor'].includes(mode)
    || ['confirmation_required', 'login_required'].includes(String(action?.type || ''))
  );
  const showConversationText = !hasTaskCard || (!presentationResult && !action);

  useEffect(() => {
    const onSelectionChange = () => setSelection(window.getSelection()?.toString().trim() || '');
    document.addEventListener('selectionchange', onSelectionChange);
    return () => document.removeEventListener('selectionchange', onSelectionChange);
  }, []);

  return (
    <div className="chat-message-renderer">
      {!hasTaskCard && streaming && !content && <div data-testid="chat-streaming-placeholder" className="inline-flex items-center gap-2 rounded-xl bg-slate-50 px-3 py-2 text-xs font-bold text-slate-500 dark:bg-slate-900/70 dark:text-slate-300"><span className="h-2 w-2 animate-pulse rounded-full bg-cyan-500" />正在生成回答</div>}
      {showConversationText && <MarkdownBlocks content={content} />}
      {!hasTaskCard && streaming && content && <span data-testid="chat-streaming-cursor" className="ml-1 inline-block h-4 w-1.5 animate-pulse align-[-2px] bg-cyan-500" />}
      {hasTaskCard && (
        <TaskStatusCard
          message={message}
          result={presentationResult}
          sessionId={sessionId}
          resumeReady={resumeReady}
          onLogin={onLogin}
          onResume={onResume}
          onCancel={onCancel}
          onRetry={onRetry}
          onClarification={onClarification}
          onConfirmAction={onConfirmAction}
          onDeleted={(artifactId) => setDeletedArtifactIds((current) => new Set(current).add(artifactId))}
        />
      )}
      {!hasTaskCard && presentationResult && (
        <PresentationResultCard
          result={presentationResult}
          sessionId={sessionId}
          onDeleted={(artifactId) => setDeletedArtifactIds((current) => new Set(current).add(artifactId))}
        />
      )}
      {!presentationResult && resultPreference && (
        <UserFacingResultCard
          result={resultPreference as UserFacingResult}
          sessionId={sessionId}
          onDeleted={(artifactId) => setDeletedArtifactIds((current) => new Set(current).add(artifactId))}
        />
      )}
      {!hasTaskCard && action?.type === 'login_required' && (
        <div data-testid="gscloud-login-required" className="mt-3 rounded-2xl border border-amber-300/35 bg-amber-100/45 p-3 dark:bg-amber-400/10">
          <div className="text-sm font-black">需要登录地理空间数据云账号</div>
          <div className="mt-2 flex flex-wrap gap-2">
            {!resumeReady && <button type="button" onClick={() => onLogin?.(jobId)} className="glass-button inline-flex items-center gap-1.5 px-3 py-2 text-xs font-black"><LogIn size={14} />去登录</button>}
            {resumeReady && <button type="button" onClick={() => onResume?.(jobId)} className="glass-button inline-flex items-center gap-1.5 px-3 py-2 text-xs font-black text-emerald-700"><Play size={14} />继续下载</button>}
            <button type="button" onClick={() => onCancel?.(jobId)} className="glass-button inline-flex items-center gap-1.5 px-3 py-2 text-xs font-black text-coral"><XCircle size={14} />取消任务</button>
          </div>
        </div>
      )}
      {!hasTaskCard && action?.type === 'clarification_required' && Array.isArray(action.options) && (
        <div data-testid="download-clarification-options" className="mt-3 flex flex-wrap gap-2">
          {action.options.map((option) => <button key={option.value} type="button" onClick={() => onClarification?.(option.value, option.label)} className="glass-button px-3 py-2 text-xs font-black">{option.label}</button>)}
        </div>
      )}
      {!hasTaskCard && action?.type === 'confirmation_required' && confirmationPrompt && confirmedActionId && (
        <div data-testid="download-confirmation-required" className="mt-3 rounded-2xl border border-amber-300/35 bg-amber-100/45 p-3 dark:bg-amber-400/10">
          <div className="text-sm font-black">需要确认后执行</div>
          <p className="mt-1 text-xs leading-5 text-slate-600 dark:text-slate-300">{String(action.message || '请确认产品、区域、账号、费用和覆盖风险后再继续。')}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => onConfirmAction?.(confirmationPrompt, confirmedActionId)}
              className="glass-button inline-flex items-center gap-1.5 px-3 py-2 text-xs font-black text-emerald-700"
            >
              <ShieldCheck size={14} />确认执行
            </button>
          </div>
        </div>
      )}
      {!presentationResult && !userResult && visibleArtifacts.length > 0 && (
        <div data-testid="artifact-download-list" className="artifact-download-list">
          {visibleArtifacts.map((artifact) => (
            <ArtifactDownloadCard
              key={artifactKey(artifact)}
              artifact={artifact}
              sessionId={sessionId}
              onDeleted={(artifactId) => setDeletedArtifactIds((current) => new Set(current).add(artifactId))}
            />
          ))}
        </div>
      )}
      {!isUser && !isSystem && (
        <div data-testid="chat-message-actions" className="chat-message-actions">
          <CopyButton text={content} label="复制" testId="copy-message" />
          {selection && (
            <button
              type="button"
              className={cn('chat-copy-button', copied && 'is-copied')}
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                copyText(selection);
              }}
              title="复制选中文本"
            >
              {copied ? <Check size={13} /> : <Clipboard size={13} />}
              <span>{copied ? '已复制' : '复制选中文本'}</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}
