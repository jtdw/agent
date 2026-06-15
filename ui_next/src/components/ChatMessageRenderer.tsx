import { Check, Clipboard, Copy, LogIn, Play, XCircle } from 'lucide-react';
import { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeSanitize from 'rehype-sanitize';
import remarkGfm from 'remark-gfm';
import { type ChatArtifact, type ChatMessage } from '@/lib/api';
import { ArtifactDownloadCard } from './ArtifactDownloadCard';
import { cn } from '@/lib/cn';

function useCopyToast() {
  const [copied, setCopied] = useState(false);
  const copyText = async (text: string) => {
    setCopied(true);
    window.setTimeout(() => setCopied(false), 3000);
    const safeText = String(text || '');
    try {
      await navigator.clipboard.writeText(safeText);
    } catch {
      try {
        const target = document.createElement('textarea');
        target.value = safeText;
        target.setAttribute('readonly', 'true');
        target.style.position = 'fixed';
        target.style.left = '-9999px';
        document.body.appendChild(target);
        target.select();
        document.execCommand('copy');
        target.remove();
      } catch {
        // Some browsers block both clipboard APIs in automation or hardened contexts.
      }
    }
  };
  return { copied, copyText };
}

function CopyButton({ text, label, testId }: { text: string; label: string; testId?: string }) {
  const { copied, copyText } = useCopyToast();
  const showCopied = () => {
    copyText('');
  };
  const runCopy = (event: { preventDefault: () => void; stopPropagation: () => void }) => {
    event.preventDefault();
    event.stopPropagation();
    copyText(text);
  };
  return (
    <button
      data-testid={testId}
      type="button"
      onPointerDown={showCopied}
      onClick={runCopy}
      className={cn('chat-copy-button', copied && 'is-copied')}
      title={copied ? '已复制' : label}
    >
      {copied ? <Check size={13} /> : <Copy size={13} />}
      <span>{copied ? '已复制' : label}</span>
    </button>
  );
}

function MarkdownBlocks({ content }: { content: string }) {
  return (
    <div className="chat-markdown" data-list-bullet="•">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize]}
        components={{
          code({ inline, className, children, ...props }: any) {
            const value = String(children || '').replace(/\n$/, '');
            if (inline) {
              return <code className="chat-inline-code" {...props}>{children}</code>;
            }
            const lang = /language-([\w-]+)/.exec(className || '')?.[1] || 'code';
            return (
              <div className="chat-code-block">
                <div className="chat-code-toolbar">
                  <span>{lang}</span>
                  <CopyButton text={value} label="复制代码" testId="copy-code" />
                </div>
                <pre><code className={className} {...props}>{children}</code></pre>
              </div>
            );
          },
          table({ children }) {
            return <div className="chat-table-wrap"><table>{children}</table></div>;
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function artifactsFromMessage(message: ChatMessage): ChatArtifact[] {
  return (message.meta?.artifacts || []).filter((item): item is ChatArtifact => Boolean(item?.artifact_id && item?.download_url));
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
  onClarification
}: {
  message: ChatMessage;
  content: string;
  isUser?: boolean;
  isSystem?: boolean;
  resumeReady?: boolean;
  onLogin?: (jobId: string) => void;
  onResume?: (jobId: string) => void;
  onCancel?: (jobId: string) => void;
  onClarification?: (value: string, label: string) => void;
}) {
  const artifacts = artifactsFromMessage(message);
  const [deletedArtifactIds, setDeletedArtifactIds] = useState<Set<string>>(() => new Set());
  const visibleArtifacts = artifacts.filter((artifact) => !deletedArtifactIds.has(artifact.artifact_id));
  const [selection, setSelection] = useState('');
  const { copied, copyText } = useCopyToast();
  const action = message.meta?.action_required;
  const jobId = String(action?.job_id || '');

  useEffect(() => {
    const onSelectionChange = () => setSelection(window.getSelection()?.toString().trim() || '');
    document.addEventListener('selectionchange', onSelectionChange);
    return () => document.removeEventListener('selectionchange', onSelectionChange);
  }, []);

  return (
    <div className="chat-message-renderer">
      <MarkdownBlocks content={content} />
      {action?.type === 'login_required' && (
        <div data-testid="gscloud-login-required" className="mt-3 rounded-2xl border border-amber-300/35 bg-amber-100/45 p-3 dark:bg-amber-400/10">
          <div className="text-sm font-black">需要登录地理空间数据云账号</div>
          <div className="mt-2 flex flex-wrap gap-2">
            {!resumeReady && <button type="button" onClick={() => onLogin?.(jobId)} className="glass-button inline-flex items-center gap-1.5 px-3 py-2 text-xs font-black"><LogIn size={14} />去登录</button>}
            {resumeReady && <button type="button" onClick={() => onResume?.(jobId)} className="glass-button inline-flex items-center gap-1.5 px-3 py-2 text-xs font-black text-emerald-700"><Play size={14} />继续下载</button>}
            <button type="button" onClick={() => onCancel?.(jobId)} className="glass-button inline-flex items-center gap-1.5 px-3 py-2 text-xs font-black text-coral"><XCircle size={14} />取消任务</button>
          </div>
        </div>
      )}
      {action?.type === 'clarification_required' && Array.isArray(action.options) && (
        <div data-testid="download-clarification-options" className="mt-3 flex flex-wrap gap-2">
          {action.options.map((option) => <button key={option.value} type="button" onClick={() => onClarification?.(option.value, option.label)} className="glass-button px-3 py-2 text-xs font-black">{option.label}</button>)}
        </div>
      )}
      {visibleArtifacts.length > 0 && (
        <div data-testid="artifact-download-list" className="artifact-download-list">
          {visibleArtifacts.map((artifact) => (
            <ArtifactDownloadCard
              key={artifact.artifact_id || artifact.download_url}
              artifact={artifact}
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
