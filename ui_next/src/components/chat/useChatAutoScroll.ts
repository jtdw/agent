import { useEffect, useRef, type UIEvent } from 'react';

type UseChatAutoScrollArgs = {
  messages: unknown[];
  thinking: boolean;
};

export function useChatAutoScroll({ messages, thinking }: UseChatAutoScrollArgs) {
  const listRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);

  useEffect(() => {
    if (!stickToBottomRef.current) return;
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, thinking]);

  const handleScroll = (event: UIEvent<HTMLDivElement>) => {
    const target = event.currentTarget;
    stickToBottomRef.current = target.scrollHeight - target.scrollTop - target.clientHeight < 96;
  };

  return { listRef, handleScroll };
}
