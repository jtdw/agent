import { ChevronDown, Database, Download, FileBarChart, Image as ImageIcon, Layers, ListChecks, Package } from 'lucide-react';
import { useState } from 'react';
import { type ChatArtifact, type PresentationResult } from '@/lib/api';
import { ArtifactDownloadCard } from '../../ArtifactDownloadCard';

function artifactKey(artifact: ChatArtifact) {
  return artifact.artifact_id || artifact.filename || artifact.title || '成果文件';
}

function stableTextKey(prefix: string, value: unknown) {
  const text = String(value || '');
  let hash = 0;
  for (let i = 0; i < text.length; i += 1) {
    hash = ((hash << 5) - hash + text.charCodeAt(i)) | 0;
  }
  return `${prefix}-${Math.abs(hash).toString(36)}-${text.length}`;
}

function artifactFromRef(ref: { artifact_id: string; title?: string; type?: string; source_step_id?: string; source_tool?: string }, kind = ''): ChatArtifact {
  return {
    artifact_id: ref.artifact_id,
    title: ref.title || ref.artifact_id,
    name: ref.title || ref.artifact_id,
    type: ref.type || kind,
    kind: kind || ref.type || '成果文件',
    source: { tool_name: ref.source_tool, workflow_id: ref.source_step_id },
  };
}

function presentationArtifacts(result: PresentationResult) {
  const seen = new Set<string>();
  const add = (artifact: ChatArtifact) => {
    if (!artifact.artifact_id || seen.has(artifact.artifact_id)) return null;
    seen.add(artifact.artifact_id);
    return artifact;
  };
  return [
    ...(result.artifact_refs || []).map((ref) => add(artifactFromRef(ref))).filter(Boolean) as ChatArtifact[],
    ...(result.image_refs || []).map((ref) => add(artifactFromRef({ ...ref, type: 'image' }, 'image'))).filter(Boolean) as ChatArtifact[],
  ];
}

function groupPresentationArtifacts(result: PresentationResult) {
  const artifacts = presentationArtifacts(result);
  const imageIds = new Set((result.image_refs || []).map((item) => item.artifact_id));
  const modelOrReport = artifacts.filter((artifact) => /model|report|metrics|pdf|md|json/i.test(`${artifact.type || ''} ${artifact.title || ''}`));
  const images = artifacts.filter((artifact) => imageIds.has(artifact.artifact_id) || /image|plot|png|jpg|jpeg|webp/i.test(`${artifact.type || ''} ${artifact.title || ''}`));
  const data = artifacts.filter((artifact) => !modelOrReport.some((item) => item.artifact_id === artifact.artifact_id) && !images.some((item) => item.artifact_id === artifact.artifact_id));
  const recommended = artifacts.slice(0, 5);
  return [
    { id: 'recommended', title: '推荐查看', icon: ListChecks, artifacts: recommended },
    { id: 'data', title: '数据结果', icon: Database, artifacts: data },
    { id: 'images', title: '图像预览', icon: ImageIcon, artifacts: images },
    { id: 'models', title: '模型与报告', icon: FileBarChart, artifacts: modelOrReport },
  ];
}

export function TaskResultGroups({
  result,
  sessionId,
  onDeleted,
}: {
  result: PresentationResult;
  sessionId?: string;
  onDeleted?: (artifactId: string) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const groups = groupPresentationArtifacts(result);
  const allArtifacts = presentationArtifacts(result);
  const visibleGroups = groups.map((group) => ({ ...group, artifacts: showAll ? group.artifacts : group.artifacts.slice(0, group.id === 'recommended' ? 5 : 3) }));
  const visibleNextActions = (result.next_action_suggestions || []).slice(0, showAll ? 8 : 3);
  if (!allArtifacts.length && !(result.map_layer_refs || []).length && !(result.table_refs || []).length && !visibleNextActions.length) return null;
  return (
    <section data-testid="result-groups" className="mt-4 space-y-3 rounded-[20px] border border-slate-200/80 bg-slate-50/70 p-3 dark:border-slate-800 dark:bg-slate-950/28">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <div className="grid h-8 w-8 place-items-center rounded-2xl bg-white text-blue-600 shadow-sm dark:bg-slate-900 dark:text-cyan-300">
            <Package size={15} />
          </div>
          <div>
            <div className="text-sm font-black text-slate-900 dark:text-slate-100">任务结果</div>
            <div className="text-[11px] font-semibold text-slate-500 dark:text-slate-400">
              {allArtifacts.length} 个文件 · {(result.map_layer_refs || []).length} 个图层 · {(result.table_refs || []).length} 个表格
            </div>
          </div>
        </div>
        {allArtifacts.length > 5 && (
          <button type="button" onClick={() => setShowAll((value) => !value)} className="chat-copy-button">
            <ChevronDown size={13} /> {showAll ? '收起全部结果' : '展开全部结果'}
          </button>
        )}
      </div>
      {allArtifacts.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {allArtifacts[0] && <ArtifactDownloadCard artifact={{ ...allArtifacts[0], title: `下载推荐结果：${allArtifacts[0].title || allArtifacts[0].artifact_id}` }} sessionId={sessionId} onDeleted={onDeleted} />}
          {allArtifacts.length > 1 && (
            <button type="button" onClick={() => setShowAll(true)} className="chat-copy-button">
              <Download size={13} /> 下载全部结果
            </button>
          )}
        </div>
      )}
      {visibleGroups.map((group) => {
        const Icon = group.icon;
        if (!group.artifacts.length) return null;
        return (
          <div key={group.id} data-testid={`result-group-${group.id}`} className="rounded-2xl border border-slate-200/75 bg-white/78 p-3 dark:border-slate-800 dark:bg-slate-950/35">
            <div className="mb-2 flex items-center justify-between gap-2 text-xs font-black text-slate-600 dark:text-slate-300">
              <span className="inline-flex items-center gap-2"><Icon size={14} />{group.title}</span>
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500 dark:bg-slate-900 dark:text-slate-400">{group.artifacts.length}</span>
            </div>
            <div className="artifact-download-list">
              {group.artifacts.map((artifact) => (
                <ArtifactDownloadCard key={artifactKey(artifact)} artifact={artifact} sessionId={sessionId} onDeleted={onDeleted} />
              ))}
            </div>
          </div>
        );
      })}
      {Boolean(result.map_layer_refs?.length) && (
        <div className="rounded-2xl border border-slate-200/75 bg-white/78 p-3 text-xs leading-5 text-slate-600 dark:border-slate-800 dark:bg-slate-950/35 dark:text-slate-300">
          <div className="mb-1 flex items-center gap-2 font-black"><Layers size={14} />地图图层</div>
          {result.map_layer_refs?.slice(0, showAll ? 20 : 5).map((layer) => <div key={layer.layer_id}>{layer.name || layer.layer_id}</div>)}
        </div>
      )}
      {Boolean(result.table_refs?.length) && (
        <div className="rounded-2xl border border-slate-200/75 bg-white/78 p-3 text-xs leading-5 text-slate-600 dark:border-slate-800 dark:bg-slate-950/35 dark:text-slate-300">
          <div className="mb-1 flex items-center gap-2 font-black"><Database size={14} />表格结果</div>
          {result.table_refs?.slice(0, showAll ? 20 : 5).map((table) => <div key={table.table_id}>{table.title || table.table_id}</div>)}
        </div>
      )}
      {visibleNextActions.length > 0 && (
        <div className="rounded-2xl border border-blue-100 bg-blue-50/70 p-3 text-xs leading-5 text-blue-800 dark:border-blue-900/60 dark:bg-blue-950/25 dark:text-blue-200">
          <div className="mb-1 flex items-center gap-2 font-black"><ListChecks size={14} />下一步建议</div>
          {visibleNextActions.map((item) => <div key={stableTextKey('next-action', item)}>• {item}</div>)}
        </div>
      )}
    </section>
  );
}

export { TaskResultGroups as ResultGroups };
