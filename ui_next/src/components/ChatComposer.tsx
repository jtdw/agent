import { AtSign, Database, FileText, Image, Layers3, Loader2, Mic, Paperclip, SendHorizontal, Square, Table2 } from 'lucide-react';
import { DragEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from 'react';
import { cn } from '@/lib/cn';
import type { WorkspaceMention } from '@/lib/api';

type ChatComposerProps = {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onUpload: (files: FileList | File[]) => void;
  onStop: () => void;
  sending?: boolean;
  uploading?: boolean;
  disabled?: boolean;
  placeholder?: string;
  voiceSupported?: boolean;
  listening?: boolean;
  voiceUnavailableReason?: string;
  onVoiceToggle?: () => void;
  mentionItems?: WorkspaceMention[];
};

const minComposerHeight = 56;
const maxComposerHeight = 220;

export function ChatComposer({
  value,
  onChange,
  onSend,
  onUpload,
  onStop,
  sending = false,
  uploading = false,
  disabled = false,
  placeholder = '有问题，尽管问',
  voiceSupported = true,
  listening = false,
  voiceUnavailableReason = '当前浏览器不支持语音输入',
  onVoiceToggle,
  mentionItems = []
}: ChatComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [mentionOpen, setMentionOpen] = useState(false);
  const [mentionQuery, setMentionQuery] = useState('');
  const [mentionStart, setMentionStart] = useState<number | null>(null);
  const [activeMentionIndex, setActiveMentionIndex] = useState(0);

  const filteredMentions = useMemo(() => {
    const query = mentionQuery.trim().toLowerCase();
    const items = query
      ? mentionItems.filter((item) => `${item.name} ${item.filename || ''} ${item.type}`.toLowerCase().includes(query))
      : mentionItems;
    return items.slice(0, 10);
  }, [mentionItems, mentionQuery]);

  const syncMentionState = (nextValue: string, caret: number) => {
    const beforeCaret = nextValue.slice(0, caret);
    const match = beforeCaret.match(/@([^@\s{}]*)$/);
    if (!match) {
      setMentionOpen(false);
      setMentionQuery('');
      setMentionStart(null);
      return;
    }
    setMentionOpen(true);
    setMentionQuery(match[1] || '');
    setMentionStart(caret - match[0].length);
    setActiveMentionIndex(0);
  };

  const toggleMentionMenu = () => {
    if (mentionOpen) {
      setMentionOpen(false);
      return;
    }
    const target = textareaRef.current;
    const caret = target?.selectionStart ?? value.length;
    const nextValue = `${value.slice(0, caret)}@${value.slice(caret)}`;
    onChange(nextValue);
    setMentionOpen(true);
    setMentionQuery('');
    setMentionStart(caret);
    setActiveMentionIndex(0);
    window.requestAnimationFrame(() => {
      target?.focus();
      target?.setSelectionRange(caret + 1, caret + 1);
    });
  };

  const selectMention = (item: WorkspaceMention) => {
    const target = textareaRef.current;
    const caret = target?.selectionStart ?? value.length;
    const start = mentionStart ?? Math.max(0, value.lastIndexOf('@', caret));
    const token = item.mention || `@{${item.name}}`;
    const nextValue = `${value.slice(0, start)}${token} ${value.slice(caret)}`;
    const nextCaret = start + token.length + 1;
    onChange(nextValue);
    setMentionOpen(false);
    setMentionQuery('');
    setMentionStart(null);
    window.requestAnimationFrame(() => {
      target?.focus();
      target?.setSelectionRange(nextCaret, nextCaret);
    });
  };

  useEffect(() => {
    const target = textareaRef.current;
    if (!target) return;
    target.style.height = `${minComposerHeight}px`;
    target.style.height = `${Math.min(maxComposerHeight, Math.max(minComposerHeight, target.scrollHeight))}px`;
    target.style.overflowY = target.scrollHeight > maxComposerHeight ? 'auto' : 'hidden';
  }, [value]);

  const submit = () => {
    if (sending) {
      onStop();
      return;
    }
    onSend();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (mentionOpen) {
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        setActiveMentionIndex((current) => filteredMentions.length ? (current + 1) % filteredMentions.length : 0);
        return;
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault();
        setActiveMentionIndex((current) => filteredMentions.length ? (current - 1 + filteredMentions.length) % filteredMentions.length : 0);
        return;
      }
      if ((event.key === 'Enter' || event.key === 'Tab') && filteredMentions.length) {
        event.preventDefault();
        selectMention(filteredMentions[activeMentionIndex] || filteredMentions[0]);
        return;
      }
      if (event.key === 'Escape') {
        event.preventDefault();
        setMentionOpen(false);
        return;
      }
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    if (event.dataTransfer.files?.length) onUpload(event.dataTransfer.files);
  };

  return (
    <div
      data-testid="chat-composer"
      className={cn('chat-composer-shell relative', dragging && 'is-dragging')}
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
    >
      {mentionOpen && (
        <div data-testid="chat-mention-menu" className="chat-mention-menu" role="listbox" aria-label="已上传的数据">
          <div className="chat-mention-header">
            <span>引用工作区数据</span>
            <span>{mentionItems.length}</span>
          </div>
          {filteredMentions.length ? (
            <div className="chat-mention-list">
              {filteredMentions.map((item, index) => {
                const Icon = item.type === 'table' ? Table2 : item.type === 'vector' ? Layers3 : item.type === 'raster' ? Image : item.type === 'document' ? FileText : Database;
                const details = [item.type, item.row_count != null ? `${item.row_count} 行` : '', item.column_count != null ? `${item.column_count} 字段` : '', item.crs || ''].filter(Boolean).join(' · ');
                return (
                  <button
                    key={item.id || item.name}
                    type="button"
                    role="option"
                    aria-selected={index === activeMentionIndex}
                    className={cn('chat-mention-item', index === activeMentionIndex && 'is-active')}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => selectMention(item)}
                    onMouseEnter={() => setActiveMentionIndex(index)}
                  >
                    <Icon size={17} strokeWidth={1.7} />
                    <span className="min-w-0 flex-1">
                      <strong>{item.name}</strong>
                      <small>{details || item.filename || '工作区数据'}</small>
                    </span>
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="chat-mention-empty">{mentionItems.length ? '没有匹配的数据' : '当前工作区还没有已上传数据'}</div>
          )}
        </div>
      )}
      <button
        type="button"
        className="chat-composer-tool"
        onClick={() => fileInputRef.current?.click()}
        disabled={disabled || uploading}
        title={uploading ? '上传中' : '上传文件'}
        aria-label={uploading ? '上传中' : '上传文件'}
      >
        {uploading ? <Loader2 size={18} className="animate-spin" /> : <Paperclip size={18} />}
      </button>
      <button
        data-testid="chat-mention-trigger"
        type="button"
        className={cn('chat-composer-tool', mentionOpen && 'is-active')}
        onClick={toggleMentionMenu}
        disabled={disabled}
        title="引用已上传的数据"
        aria-label="引用已上传的数据"
      >
        <AtSign size={18} />
      </button>
      <textarea
        ref={textareaRef}
        data-testid="chat-input"
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
          syncMentionState(event.target.value, event.target.selectionStart);
        }}
        onKeyDown={onKeyDown}
        disabled={disabled}
        rows={1}
        aria-label="聊天输入框，Enter 发送，Shift+Enter 换行"
        placeholder={placeholder}
        className="chat-composer-textarea"
      />
      <button
        data-testid="chat-voice"
        type="button"
        onClick={onVoiceToggle}
        disabled={disabled || !onVoiceToggle || !voiceSupported}
        className={cn('chat-composer-tool', listening && 'is-active')}
        title={voiceSupported ? (listening ? '停止语音输入' : '语音输入') : voiceUnavailableReason}
        aria-label={voiceSupported ? (listening ? '停止语音输入' : '语音输入') : voiceUnavailableReason}
      >
        <Mic size={18} />
      </button>
      <button
        data-testid={sending ? 'chat-stop' : 'chat-send'}
        type="button"
        onClick={submit}
        disabled={disabled || (!sending && !value.trim())}
        className={cn('chat-composer-submit', sending && 'is-stopping')}
        title={sending ? '停止等待本次回复' : '发送，Shift+Enter 换行'}
        aria-label={sending ? '停止等待本次回复' : '发送'}
      >
        {sending ? <Square size={17} fill="currentColor" /> : <SendHorizontal size={18} />}
      </button>
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        accept=".zip,.shp,.shx,.dbf,.prj,.cpg,.geojson,.gpkg,.kml,.csv,.xlsx,.xls,.tif,.tiff,.img,.docx,.txt,.md,.json,.png,.jpg,.jpeg"
        onChange={(event) => {
          if (event.target.files?.length) onUpload(event.target.files);
          event.currentTarget.value = '';
        }}
      />
    </div>
  );
}
