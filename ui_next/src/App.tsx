import { lazy, Suspense, useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Database, MessageCircle, PanelRightOpen, Sparkles } from 'lucide-react';
import { MapControls } from './components/MapControls';
import { SplashScreen } from './components/SplashScreen';
import { useTheme } from './hooks/useTheme';
import { api, type CommercialUser, type ResultMapLayer, type ResultPanel } from './lib/api';
import { clearStoredAuth, readStoredUser, writeStoredUser } from './lib/authStorage';
import { mergeChatContext, type ChatContextPayload } from './lib/chatContext';
import type { MapCommand, MapCommandType } from './components/mapCommands';
import type { ParsedMapTextCommand } from './components/mapTextCommands';
import type { WorkflowAction } from './components/researchWorkflow';
import { mergeResultLayerState, nextPaletteName, resultLayerKey, type ResultLayerLike, type ResultLayerPaletteName, type ResultLayerPalettePreferences, type ResultLayerPaletteTarget, type ResultLayerStateMap } from './components/mapLayerPolicy';

const MapStage = lazy(() => import('./components/MapStage').then((m) => ({ default: m.MapStage })));
const ChatPanel = lazy(() => import('./components/ChatPanel').then((m) => ({ default: m.ChatPanel })));
const LayerPanel = lazy(() => import('./components/LayerPanel').then((m) => ({ default: m.LayerPanel })));
const SettingsPanel = lazy(() => import('./components/SettingsPanel').then((m) => ({ default: m.SettingsPanel })));
const AnalysisPanel = lazy(() => import('./components/AnalysisPanel').then((m) => ({ default: m.AnalysisPanel })));
const ProductConsole = lazy(() => import('./components/ProductConsole').then((m) => ({ default: m.ProductConsole })));

function MapFallback() {
  return (
    <div className="absolute inset-0 bg-[radial-gradient(circle_at_22%_20%,rgba(34,211,238,.24),transparent_28%),linear-gradient(135deg,#eef7ff,#d9e8f7_48%,#eef2ff)] dark:bg-[radial-gradient(circle_at_22%_20%,rgba(34,211,238,.18),transparent_30%),linear-gradient(135deg,#07111f,#101827_58%,#07111f)]">
      <div className="absolute left-1/2 top-1/2 h-11 w-11 -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-white/40 bg-white/50 p-2 shadow-glass backdrop-blur-2xl dark:border-white/10 dark:bg-white/10">
        <div className="h-full w-full animate-spin rounded-xl border-2 border-cyan-glow/30 border-t-cyan-glow" />
      </div>
    </div>
  );
}

function PanelFallback({ side }: { side: 'left' | 'right' }) {
  return (
    <div className={`no-drag fixed top-10 z-30 h-48 w-[min(380px,calc(100vw-1.5rem))] rounded-[28px] border border-white/45 bg-white/55 p-4 shadow-glass backdrop-blur-2xl dark:border-white/10 dark:bg-slate-950/50 ${side === 'left' ? 'left-3 sm:left-4' : 'right-3 sm:right-4'}`}>
      <div className="h-5 w-28 rounded-full bg-white/60 dark:bg-white/10" />
      <div className="mt-4 space-y-3">
        <div className="h-10 rounded-2xl bg-white/45 dark:bg-white/5" />
        <div className="h-10 rounded-2xl bg-white/35 dark:bg-white/5" />
        <div className="h-10 rounded-2xl bg-white/25 dark:bg-white/5" />
      </div>
    </div>
  );
}

function resultLayerMatchesTarget(layer: ResultLayerLike, target: ResultLayerPaletteTarget) {
  return target === 'all'
    || String(layer.kind || '').toLowerCase() === target
    || String(layer.name || '').toLowerCase().includes(String(target).toLowerCase());
}

export default function App() {
  const { theme, toggle } = useTheme();
  const [splash, setSplash] = useState(true);
  const [user, setUser] = useState<CommercialUser | null>(null);
  const [basemap, setBasemap] = useState<'standard' | 'satellite' | 'terrain' | 'dark'>('standard');
  const [consoleOpen, setConsoleOpen] = useState(true);
  const [chatOpen, setChatOpen] = useState(false);
  const [toolsOpen, setToolsOpen] = useState(false);
  const [drawMode, setDrawMode] = useState(false);
  const [layerVisibility, setLayerVisibility] = useState({ dem: true, boundary: true, stations: true, soil: true });
  const [resultLayers, setResultLayers] = useState<ResultMapLayer[]>([]);
  const [resultLayerState, setResultLayerState] = useState<ResultLayerStateMap>({});
  const [resultLayerPalettePreferences, setResultLayerPalettePreferences] = useState<ResultLayerPalettePreferences>({});
  const [mapCommand, setMapCommand] = useState<MapCommand | null>(null);
  const [externalPrompt, setExternalPrompt] = useState<{ id: number; prompt: string } | null>(null);
  const [latestResultPanel, setLatestResultPanel] = useState<ResultPanel | null>(null);
  const [chatContext, setChatContext] = useState<ChatContextPayload>({});
  const [currentSessionId, setCurrentSessionId] = useState('');
  const updateChatContext = (patch: Partial<ChatContextPayload>) => setChatContext((current) => mergeChatContext(current, patch));

  const dispatchMapCommand = (type: MapCommandType) => {
    setMapCommand({ type, id: Date.now() });
  };

  const handleTextMapCommand = (command: ParsedMapTextCommand) => {
    if (command.kind === 'map') {
      dispatchMapCommand(command.command);
      return command.reply;
    }
    if (command.kind === 'layer') {
      if (command.layer === 'stations' || command.layer === 'boundary') {
        setLayerVisibility((v) => ({ ...v, [command.layer]: command.visible }));
      }
      setResultLayerState((current) => {
        const merged = mergeResultLayerState(resultLayers, current, resultLayerPalettePreferences);
        const next = { ...merged };
        resultLayers.forEach((layer, index) => {
          if (layer.kind !== command.layer) return;
          const key = resultLayerKey(layer, String(index));
          next[key] = { ...next[key], visible: command.visible };
        });
        return next;
      });
      return command.reply;
    }
    if (command.kind === 'style') {
      const target = command.target;
      const targetLayer = resultLayers.find((layer) => resultLayerMatchesTarget(layer, target));
      const targetKey = targetLayer ? resultLayerKey(targetLayer, String(resultLayers.indexOf(targetLayer))) : '';
      const currentPalette = targetKey ? resultLayerState[targetKey]?.palette : undefined;
      const selectedPalette = command.palette || nextPaletteName(currentPalette, Math.floor(Math.random() * 5) + 1);
      const nextPreferences: ResultLayerPalettePreferences = { ...resultLayerPalettePreferences, [target]: selectedPalette };
      setResultLayerPalettePreferences(nextPreferences);
      setResultLayerState((current) => {
        const merged = mergeResultLayerState(resultLayers, current, nextPreferences);
        const next = { ...merged };
        resultLayers.forEach((layer, index) => {
          const key = resultLayerKey(layer, String(index));
          const matches = resultLayerMatchesTarget(layer, target);
          if (!matches) return;
          next[key] = {
            visible: next[key]?.visible ?? true,
            removed: next[key]?.removed ?? false,
            palette: selectedPalette
          };
        });
        return next;
      });
      return command.reply;
    }
    if (command.kind === 'draw') {
      if (command.action === 'clear') dispatchMapCommand('clearDraw');
      if (command.action === 'start') setDrawMode(true);
      if (command.action === 'stop') setDrawMode(false);
      return command.reply;
    }
    return '';
  };

  const runWorkflowAction = (action: WorkflowAction) => {
    if (action.kind === 'prompt' || action.kind === 'workflow') {
      setChatOpen(true);
      setExternalPrompt({ id: Date.now(), prompt: action.prompt });
      return;
    }
    if (action.kind === 'map') {
      dispatchMapCommand(action.command);
      return;
    }
    if (action.kind === 'layer') {
      setLayerVisibility((v) => ({ ...v, [action.layer]: action.visible }));
    }
  };

  useEffect(() => {
    const t = window.setTimeout(() => setSplash(false), 2000);
    return () => window.clearTimeout(t);
  }, []);

  useEffect(() => {
    const saved = readStoredUser();
    if (saved) setUser(saved);
    let cancelled = false;
    api.me()
      .then((result) => {
        if (cancelled) return;
        if (result.authenticated && result.user) {
          setUser(result.user);
          writeStoredUser(result.user);
          return;
        }
        clearStoredAuth();
        setUser(null);
      })
      .catch(() => {
        if (cancelled) return;
        // Keep the locally restored user when the backend is temporarily unavailable.
        // The next authenticated API call will still be checked by the server.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!user) setCurrentSessionId('');
  }, [user]);

  const syncResultLayers = (layers: ResultMapLayer[]) => {
    setResultLayers(layers);
    setResultLayerState((current) => mergeResultLayerState(layers, current, resultLayerPalettePreferences));
  };

  const updateResultLayer = (layerId: string, patch: Partial<{ visible: boolean; removed: boolean; palette: ResultLayerPaletteName }>) => {
    setResultLayerState((current) => ({
      ...current,
      [layerId]: {
        visible: current[layerId]?.visible ?? true,
        removed: current[layerId]?.removed ?? false,
        palette: current[layerId]?.palette || 'cyan',
        ...patch
      }
    }));
  };

  return (
    <div className="relative isolate h-screen w-screen overflow-hidden text-slate-950 transition-colors duration-500 dark:text-slate-50">
      <SplashScreen visible={splash} />
      <Suspense fallback={<MapFallback />}>
        <MapStage theme={theme} basemap={basemap} userId={user?.user_id || ''} sessionId={currentSessionId} drawMode={drawMode} setDrawMode={setDrawMode} layerVisibility={layerVisibility} resultLayerState={resultLayerState} mapCommand={mapCommand} onResultLayersChange={syncResultLayers} onChatContextChange={updateChatContext} />
      </Suspense>
      <Suspense fallback={chatOpen ? <PanelFallback side="left" /> : null}>
        <AnimatePresence>
          {chatOpen && <ChatPanel user={user} setUser={setUser} onClose={() => setChatOpen(false)} onMapTextCommand={handleTextMapCommand} externalPrompt={externalPrompt} onResultPanel={setLatestResultPanel} onSessionChange={setCurrentSessionId} chatContext={chatContext} />}
        </AnimatePresence>
      </Suspense>
      <Suspense fallback={toolsOpen ? <PanelFallback side="right" /> : null}>
        <AnimatePresence>
          {toolsOpen && (
            <LayerPanel
              user={user}
              sessionId={currentSessionId}
              basemap={basemap}
              setBasemap={setBasemap}
              onClose={() => setToolsOpen(false)}
              layerVisibility={layerVisibility}
              resultLayers={resultLayers}
              resultLayerState={resultLayerState}
              onLayerToggle={(id) => setLayerVisibility((v) => ({ ...v, [id]: !v[id as keyof typeof v] }))}
              onResultLayerChange={updateResultLayer}
              onLayerLocate={(id) => setMapCommand({ type: 'locateLayer', id: Date.now(), layerId: id })}
              onRunWorkflowAction={runWorkflowAction}
            />
          )}
        </AnimatePresence>
      </Suspense>
      <Suspense fallback={null}>
        {!consoleOpen && (
          <>
            <SettingsPanel />
            <AnalysisPanel userId={user?.user_id || ''} resultPanel={latestResultPanel} onChatContextChange={updateChatContext} />
          </>
        )}
      </Suspense>
      <Suspense fallback={null}>
        {consoleOpen && (
          <ProductConsole
            user={user}
            setUser={setUser}
            sessionId={currentSessionId}
            resultPanel={latestResultPanel}
            onOpenChat={() => setChatOpen(true)}
            onMapTextCommand={handleTextMapCommand}
            externalPrompt={externalPrompt}
            onResultPanel={setLatestResultPanel}
            onSessionChange={setCurrentSessionId}
            chatContext={chatContext}
            onOpenMap={() => {
              setConsoleOpen(false);
              setChatOpen(true);
              setToolsOpen(true);
            }}
          />
        )}
      </Suspense>
      {!consoleOpen && <MapControls theme={theme} toggleTheme={toggle} drawMode={drawMode} toggleDrawMode={() => setDrawMode((v) => !v)} onMapCommand={dispatchMapCommand} />}

      {!consoleOpen && (
        <motion.div
          initial={{ opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          className="no-drag fixed bottom-5 right-5 z-40 flex items-center gap-2 rounded-[24px] border border-white/50 bg-white/70 p-2 shadow-glass backdrop-blur-2xl dark:border-white/10 dark:bg-slate-950/65"
        >
          <div className="hidden items-center gap-2 px-2 text-xs font-black text-slate-500 dark:text-slate-300 sm:flex">
            <Sparkles size={14} strokeWidth={1.7} /> 工作台
          </div>
          <button
            onClick={() => {
              setConsoleOpen(true);
              setChatOpen(false);
              setToolsOpen(false);
            }}
            className="floating-dock-button"
            title="打开控制台"
          >
            <PanelRightOpen size={18} strokeWidth={1.7} />
          </button>
          <button
            onClick={() => setChatOpen((v) => !v)}
            className={`floating-dock-button ${chatOpen ? 'is-active' : ''}`}
            title={chatOpen ? '隐藏智能助手' : '显示智能助手'}
          >
            <MessageCircle size={19} strokeWidth={1.7} />
          </button>
          <button
            onClick={() => setToolsOpen((v) => !v)}
            className={`floating-dock-button ${toolsOpen ? 'is-active' : ''}`}
            title={toolsOpen ? '隐藏数据与工具' : '显示数据与工具'}
          >
            <Database size={18} strokeWidth={1.7} />
          </button>
          {!chatOpen && !toolsOpen && (
          <button
            onClick={() => {
              setChatOpen(true);
              setToolsOpen(true);
            }}
            className="floating-dock-button"
            title="恢复工作台"
          >
            <PanelRightOpen size={18} strokeWidth={1.7} />
          </button>
          )}
        </motion.div>
      )}
    </div>
  );
}
