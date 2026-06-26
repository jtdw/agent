import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react';
import { isLocalSecureContext } from '../mapLayerPolicy';

type SpeechRecognitionInstance = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  onresult: ((event: { results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
};

type UseChatVoiceInputArgs = {
  setInput: Dispatch<SetStateAction<string>>;
  setError: Dispatch<SetStateAction<string>>;
};

const UNSUPPORTED_VOICE_REASON = '当前浏览器不支持语音识别。请使用 Chrome 或 Edge，并允许麦克风权限。';

export function useChatVoiceInput({ setInput, setError }: UseChatVoiceInputArgs) {
  const [listening, setListening] = useState(false);
  const [voiceSupported, setVoiceSupported] = useState(true);
  const [voiceUnavailableReason, setVoiceUnavailableReason] = useState('');
  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null);

  useEffect(() => {
    if (!isLocalSecureContext(window.location.protocol, window.location.hostname)) {
      setVoiceSupported(false);
      setVoiceUnavailableReason('浏览器只允许 HTTPS、localhost 或 127.0.0.1 页面使用麦克风。请用 http://127.0.0.1:5173 打开，或部署 HTTPS。');
      return;
    }
    const SpeechRecognition = (window as unknown as { SpeechRecognition?: new () => unknown; webkitSpeechRecognition?: new () => unknown }).SpeechRecognition
      || (window as unknown as { webkitSpeechRecognition?: new () => unknown }).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setVoiceSupported(false);
      setVoiceUnavailableReason(UNSUPPORTED_VOICE_REASON);
      return;
    }
    const recognition = new SpeechRecognition() as SpeechRecognitionInstance;
    recognition.lang = 'zh-CN';
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.onresult = (event) => {
      let finalText = '';
      let interimText = '';
      for (let i = 0; i < event.results.length; i += 1) {
        const text = event.results[i][0]?.transcript || '';
        if (event.results[i].isFinal) finalText += text;
        else interimText += text;
      }
      const text = (finalText || interimText).trim();
      if (text) setInput(text);
    };
    recognition.onerror = () => setListening(false);
    recognition.onend = () => setListening(false);
    recognitionRef.current = recognition;
    return () => recognition.stop();
  }, [setInput]);

  const toggleVoice = () => {
    if (!voiceSupported) {
      setError(voiceUnavailableReason || UNSUPPORTED_VOICE_REASON);
      return;
    }
    const recognition = recognitionRef.current;
    if (!recognition) return;
    try {
      if (listening) {
        recognition.stop();
        setListening(false);
      } else {
        setError('');
        recognition.start();
        setListening(true);
      }
    } catch {
      setListening(false);
    }
  };

  return { listening, voiceSupported, voiceUnavailableReason, toggleVoice };
}
