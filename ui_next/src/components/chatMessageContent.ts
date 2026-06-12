const EMPTY_REPLY_MESSAGE = '智能体没有返回可显示内容。请稍后重试，或换一种说法重新提问。';
const ERROR_REPLY_PREFIX = '智能体调用失败：';
const UNREADABLE_HISTORY_MESSAGE = '历史消息内容无法显示。请删除该对话，或重新提问生成新的回答。';

type MessageLike = {
  role?: string;
  content?: unknown;
  [key: string]: unknown;
};

export function assistantReplyContent(reply: unknown): string {
  const text = typeof reply === 'string' ? reply.trim() : '';
  if (isUnreadableQuestionMarkContent(text)) return UNREADABLE_HISTORY_MESSAGE;
  return text || EMPTY_REPLY_MESSAGE;
}

export function assistantErrorContent(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error || '').trim();
  return `${ERROR_REPLY_PREFIX}${message || '后端没有返回具体错误。请检查后端是否已启动。'}`;
}

export function normalizeChatMessages<T extends MessageLike>(messages: T[] | undefined | null): T[] {
  return (messages || []).map((message) => {
    if (message.role !== 'assistant') return message;
    return { ...message, content: assistantReplyContent(message.content) };
  });
}

function isUnreadableQuestionMarkContent(text: string): boolean {
  if (!text) return false;
  const questionMarkRuns = text.match(/\?{8,}/g);
  if (!questionMarkRuns) return false;
  const questionMarkCount = questionMarkRuns.join('').length;
  return questionMarkCount >= 16 && questionMarkCount / Math.max(text.length, 1) > 0.45;
}
