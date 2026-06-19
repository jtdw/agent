import { useState } from 'react';
import { api, type CapabilityResource, type CapabilityResourceType } from '../lib/api';

const RESOURCE_TYPES: CapabilityResourceType[] = ['knowledge', 'tool_cards', 'products', 'assets'];

function resourceId(item: CapabilityResource) {
  return String(item.knowledge_id || item.tool_name || item.product_id || item.asset_id || item.title || item.name || '');
}

export function CapabilityManagementPanel() {
  const [adminToken, setAdminToken] = useState('');
  const [resourceType, setResourceType] = useState<CapabilityResourceType>('knowledge');
  const [items, setItems] = useState<CapabilityResource[]>([]);
  const [query, setQuery] = useState('');
  const [searchHits, setSearchHits] = useState<Array<{ id: string; label: string }>>([]);
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setBusy(true);
    setNotice('');
    try {
      const result = await api.capabilityResources(resourceType, { include_disabled: true, admin_token: adminToken });
      setItems(result.items || []);
      setNotice(`Loaded ${result.items?.length || 0} ${resourceType} records.`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Failed to load capability resources.');
    } finally {
      setBusy(false);
    }
  };

  const uploadKnowledge = async (file: File | null) => {
    if (!file) return;
    setBusy(true);
    setNotice('');
    try {
      await api.uploadCapabilityKnowledge({ file, admin_token: adminToken, title: file.name, source: 'admin_upload', version: 'v1' });
      setNotice('Knowledge document uploaded.');
      if (resourceType === 'knowledge') await load();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Failed to upload knowledge document.');
    } finally {
      setBusy(false);
    }
  };

  const testSearch = async () => {
    if (!query.trim()) return;
    setBusy(true);
    setNotice('');
    try {
      const result = await api.testCapabilityKnowledgeSearch({ query, admin_token: adminToken });
      setSearchHits((result.items || []).map((item) => ({
        id: item.knowledge_chunk_id,
        label: `${item.title || item.knowledge_id}: ${String(item.content || '').slice(0, 90)}`
      })));
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Knowledge retrieval test failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-4 rounded-[18px] border border-white/30 bg-white/35 p-3 dark:border-white/10 dark:bg-white/5">
      <div className="mb-3">
        <div className="text-sm font-black">Knowledge & Capability Management</div>
        <div className="text-xs text-slate-500 dark:text-slate-400">Admin-only configuration for Planner context.</div>
      </div>
      <div className="space-y-2">
        <input
          value={adminToken}
          onChange={(event) => setAdminToken(event.target.value)}
          type="password"
          placeholder="Admin token"
          className="w-full rounded-2xl border border-slate-200 bg-white/75 px-3 py-2 text-sm outline-none focus:border-cyan-400 dark:border-slate-700 dark:bg-slate-950/70"
        />
        <div className="flex gap-2">
          <select
            value={resourceType}
            onChange={(event) => setResourceType(event.target.value as CapabilityResourceType)}
            className="min-w-0 flex-1 rounded-2xl border border-slate-200 bg-white/75 px-3 py-2 text-sm outline-none focus:border-cyan-400 dark:border-slate-700 dark:bg-slate-950/70"
          >
            {RESOURCE_TYPES.map((type) => (
              <option key={type} value={type}>{type}</option>
            ))}
          </select>
          <button type="button" onClick={load} disabled={busy} className="glass-button px-4 text-sm font-bold disabled:opacity-50">Load</button>
        </div>
        <label className="block rounded-2xl border border-dashed border-slate-300 bg-white/45 px-3 py-2 text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-950/40 dark:text-slate-300">
          Upload knowledge document
          <input type="file" accept=".md,.txt,.pdf,.docx" className="mt-2 block w-full text-xs" onChange={(event) => uploadKnowledge(event.target.files?.[0] || null)} />
        </label>
        <div className="flex gap-2">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Test retrieval query"
            className="min-w-0 flex-1 rounded-2xl border border-slate-200 bg-white/75 px-3 py-2 text-sm outline-none focus:border-cyan-400 dark:border-slate-700 dark:bg-slate-950/70"
          />
          <button type="button" onClick={testSearch} disabled={busy} className="glass-button px-4 text-sm font-bold disabled:opacity-50">Test</button>
        </div>
      </div>
      {notice && <div className="mt-3 rounded-2xl bg-slate-900/5 px-3 py-2 text-xs text-slate-600 dark:bg-white/5 dark:text-slate-300">{notice}</div>}
      {items.length > 0 && (
        <div className="mt-3 max-h-44 space-y-2 overflow-y-auto">
          {items.map((item) => {
            const id = resourceId(item);
            return (
              <div key={`${id}:${item.version || ''}`} className="rounded-2xl border border-white/30 bg-white/45 px-3 py-2 text-xs dark:border-white/10 dark:bg-white/5">
                <div className="font-bold">{item.title || item.display_name_zh || item.name || id}</div>
                <div className="mt-1 text-slate-500 dark:text-slate-400">{id} · {item.version || 'unversioned'} · {item.status || 'unknown'}</div>
              </div>
            );
          })}
        </div>
      )}
      {searchHits.length > 0 && (
        <div className="mt-3 space-y-2">
          {searchHits.map((hit) => (
            <div key={hit.id} className="rounded-2xl bg-cyan-500/10 px-3 py-2 text-xs text-slate-700 dark:text-slate-200">{hit.label}</div>
          ))}
        </div>
      )}
    </div>
  );
}
