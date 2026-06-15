import { motion } from 'framer-motion';
import { Archive, DatabaseZap, FolderSearch, HardDrive, RefreshCcw, Search, UploadCloud } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { api, LocalLibraryItem, LocalLibraryResponse } from '@/lib/api';
import { cn } from '@/lib/cn';
import { filterUserVisibleLibraryItems } from './localLibraryFilters';

function typeLabel(type: string) {
  const map: Record<string, string> = {
    vector: '矢量',
    raster: '栅格',
    table: '表格',
    document: '文档',
    archive: '压缩包',
    shapefile_part: '配套文件'
  };
  return map[type] || type || '未知';
}

function TypePill({ type }: { type: string }) {
  return (
    <span className="rounded-full border border-white/40 bg-white/45 px-2 py-0.5 text-[10px] font-black text-slate-600 dark:border-white/10 dark:bg-white/10 dark:text-slate-300">
      {typeLabel(type)}
    </span>
  );
}

function LibraryItemCard({
  item,
  busy,
  selected,
  onToggle,
  onImport
}: {
  item: LocalLibraryItem;
  busy: boolean;
  selected: boolean;
  onToggle: () => void;
  onImport: () => void;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn(
        'rounded-[18px] border border-white/30 bg-white/35 p-3 transition-colors dark:border-white/10 dark:bg-slate-950/20',
        selected && 'border-cyan-glow/50 bg-cyan-glow/10 shadow-glow'
      )}
    >
      <div className="flex items-start gap-3">
        <button
          onClick={onToggle}
          className={cn(
            'mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl border transition-colors',
            selected ? 'border-cyan-glow/50 bg-cyan-glow/25 text-ocean shadow-glow dark:text-cyan-glow' : 'border-white/40 bg-white/35 text-slate-500 dark:border-white/10 dark:bg-white/5 dark:text-slate-400'
          )}
          title="选择该条目"
        >
          <DatabaseZap size={16} strokeWidth={1.5} />
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <div className="truncate text-sm font-black">{item.name}</div>
            <TypePill type={item.data_type} />
          </div>
          <div className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
            {item.description || '暂无说明，可在文件库清单中补充。'}
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <span className="rounded-full bg-slate-900/5 px-2 py-0.5 text-[10px] font-bold text-slate-500 dark:bg-white/10 dark:text-slate-400">{item.category || '未分类'}</span>
            {item.region && <span className="rounded-full bg-slate-900/5 px-2 py-0.5 text-[10px] font-bold text-slate-500 dark:bg-white/10 dark:text-slate-400">{item.region}</span>}
            {item.time_range && <span className="rounded-full bg-slate-900/5 px-2 py-0.5 text-[10px] font-bold text-slate-500 dark:bg-white/10 dark:text-slate-400">{item.time_range}</span>}
            {(item.tags || []).slice(0, 3).map((tag) => (
              <span key={tag} className="rounded-full bg-cyan-glow/10 px-2 py-0.5 text-[10px] font-bold text-ocean dark:text-cyan-glow">#{tag}</span>
            ))}
          </div>
        </div>
      </div>
      <div className="mt-3 flex items-center justify-between gap-3">
        <div className="truncate text-[11px] text-slate-400" title={item.path}>{item.size_mb ? `${item.size_mb} MB · ` : ''}{item.path}</div>
        <button onClick={onImport} disabled={busy || !item.exists} className="rounded-2xl bg-gradient-to-r from-ocean to-cyan-glow px-3 py-1.5 text-xs font-black text-white shadow-glow transition-colors disabled:cursor-not-allowed disabled:opacity-50">
          载入
        </button>
      </div>
    </motion.div>
  );
}

export function LocalLibraryPanel({ userId, onImported }: { userId?: string; onImported?: () => void }) {
  const [library, setLibrary] = useState<LocalLibraryResponse | null>(null);
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('');
  const [type, setType] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');

  const refresh = async () => {
    const data = await api.localLibrary({ query, category, data_type: type });
    setLibrary(data);
    const visibleItems = filterUserVisibleLibraryItems(data.items || []);
    setSelected((ids) => ids.filter((id) => visibleItems.some((item) => item.item_id === id)));
  };

  useEffect(() => {
    refresh().catch((e) => setNotice(e instanceof Error ? e.message : '读取本地文件库失败'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [category, type]);

  useEffect(() => {
    const t = window.setTimeout(() => refresh().catch(() => undefined), 350);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query]);

  const items = useMemo(() => filterUserVisibleLibraryItems(library?.items || []), [library]);

  const rescan = async () => {
    setBusy(true);
    try {
      const r = await api.rescanLocalLibrary();
      setNotice(`扫描完成：新增 ${r.added}，更新 ${r.updated}，共 ${r.total} 条。`);
      await refresh();
    } catch (e) {
      setNotice(e instanceof Error ? e.message : '扫描失败');
    } finally {
      setBusy(false);
    }
  };

  const importIds = async (ids: string[]) => {
    if (!ids.length) {
      setNotice('请先选择要载入的本地文件库数据。');
      return;
    }
    setBusy(true);
    try {
      const r = await api.importLocalLibrary(ids, userId || '');
      setNotice(r.messages.join('；'));
      setSelected([]);
      onImported?.();
    } catch (e) {
      setNotice(e instanceof Error ? e.message : '载入失败');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-4 rounded-[22px] border border-white/30 bg-white/35 p-3 dark:border-white/10 dark:bg-slate-950/20">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-black"><HardDrive size={16} strokeWidth={1.5} /> 本地文件库</div>
          <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">可导入中国行政区划、降雨、DEM、遥感产品等初始数据。</p>
        </div>
        <button onClick={rescan} disabled={busy} className="glass-button h-9 w-9 shrink-0 rounded-2xl p-0 disabled:opacity-60" title="扫描文件库">
          <RefreshCcw size={15} strokeWidth={1.5} className={busy ? 'animate-spin' : ''} />
        </button>
      </div>

      <div className="relative">
        <Search size={15} strokeWidth={1.5} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索：行政区、降雨、DEM、站点..." className="input-glass h-10 w-full pl-9 text-xs" />
      </div>

      <div className="mt-2 grid grid-cols-2 gap-2">
        <select value={category} onChange={(e) => setCategory(e.target.value)} className="input-glass h-9 text-xs">
          <option value="">全部分类</option>
          {(library?.categories || []).map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select value={type} onChange={(e) => setType(e.target.value)} className="input-glass h-9 text-xs">
          <option value="">全部类型</option>
          {(library?.data_types || []).map((t) => <option key={t} value={t}>{typeLabel(t)}</option>)}
        </select>
      </div>

      <div className="mt-3 flex items-center justify-between text-[11px] text-slate-500 dark:text-slate-400">
        <span><FolderSearch size={13} strokeWidth={1.5} className="mr-1 inline" /> {library ? `${items.length}/${library.total} 条` : '读取中'}</span>
        <span className="truncate" title={library?.data_dir}>{library?.data_dir ? '目录：local_library/data' : ''}</span>
      </div>

      <div className="mt-3 max-h-[360px] space-y-2 overflow-y-auto pr-1">
        {items.length === 0 && (
          <div className="rounded-[18px] border border-dashed border-white/40 bg-white/25 p-4 text-center text-xs leading-5 text-slate-500 dark:border-white/10 dark:bg-white/5 dark:text-slate-400">
            <Archive size={22} strokeWidth={1.5} className="mx-auto mb-2" />
            文件库暂无条目。把数据放入后端的 <b>local_library/data</b>，再点击扫描。
          </div>
        )}
        {items.map((item) => (
          <LibraryItemCard
            key={item.item_id}
            item={item}
            busy={busy}
            selected={selected.includes(item.item_id)}
            onToggle={() => setSelected((ids) => ids.includes(item.item_id) ? ids.filter((x) => x !== item.item_id) : [...ids, item.item_id])}
            onImport={() => importIds([item.item_id])}
          />
        ))}
      </div>

      <button onClick={() => importIds(selected)} disabled={busy || selected.length === 0} className="primary-button mt-3 w-full gap-2 disabled:opacity-50">
        <UploadCloud size={16} strokeWidth={1.5} /> 载入已选数据到当前工作区{selected.length ? `（${selected.length}）` : ''}
      </button>
      {notice && <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">{notice}</p>}
      {library?.hint && <p className="mt-2 text-[11px] leading-5 text-slate-400 dark:text-slate-500">{library.hint}</p>}
    </div>
  );
}
