export const THESIS_WORKFLOW_PROMPT = '一键检查并运行闪电河流域土壤水分融合论文流程。';

export function buildRetryEditedMessageDraft(messageId: number | null, editText: string) {
  const text = editText.trim();
  if (!messageId || !text) return null;
  return {
    messageId,
    text,
  };
}
