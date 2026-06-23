import { useState } from 'react';
import { api, type AdminSystemResetMode, type CapabilityResource, type CapabilityResourceType, type DatasetAvailabilityProfile, type PlatformAccount, type StorageCleanupCandidate } from '../lib/api';

const RESOURCE_TYPES: CapabilityResourceType[] = ['knowledge', 'tool_cards', 'products', 'assets'];
const DOWNLOAD_PRODUCT_IDS = [
  'gscloud_dem_30m',
  'gscloud_dem_90m',
  'gscloud_ndvi_500m_10day',
  'gscloud_lst_1km_10day',
  'gscloud_evi_250m_10day',
  'gscloud_surface_reflectance_1km',
  'gscloud_landsat8_oli_tirs',
  'gscloud_sentinel2_msi'
];

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
  const [resetMode, setResetMode] = useState<AdminSystemResetMode>('keep_accounts');
  const [resetConfirmText, setResetConfirmText] = useState('');
  const [cleanupCandidates, setCleanupCandidates] = useState<StorageCleanupCandidate[]>([]);
  const [selectedCleanupIds, setSelectedCleanupIds] = useState<string[]>([]);
  const [cleanupConfirmText, setCleanupConfirmText] = useState('');
  const [availabilityProductId, setAvailabilityProductId] = useState('gscloud_ndvi_500m_10day');
  const [availabilityProfiles, setAvailabilityProfiles] = useState<DatasetAvailabilityProfile[]>([]);
  const [platformAccounts, setPlatformAccounts] = useState<PlatformAccount[]>([]);
  const [platformForm, setPlatformForm] = useState({
    source_key: 'gscloud',
    label: '后台地理空间数据云账号',
    username: '',
    password: '',
    daily_limit: 50,
    monthly_limit: 1000
  });
  const actor = 'admin';
  const expectedResetText = resetMode === 'keep_accounts' ? '清除用户数据' : '全部删除';
  const selectedCleanupBytes = cleanupCandidates
    .filter((item) => selectedCleanupIds.includes(item.candidate_id))
    .reduce((sum, item) => sum + Number(item.size_bytes || 0), 0);

  const formatBytes = (bytes: number) => {
    if (bytes >= 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
    if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
    if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${bytes} B`;
  };

  const healthLabel = (account: PlatformAccount) => {
    const health = account.login_health || {};
    if (health.ok) return '登录态可用';
    const reason = String(health.reason || '');
    if (reason === 'missing_storage_state') return '未保存 Cookie';
    if (reason === 'expired_gscloud_cookies') return 'Cookie 已过期';
    if (reason === 'missing_authenticated_gscloud_cookie') return '缺少认证 Cookie';
    if (reason === 'no_gscloud_cookie') return '不是 GSCloud 登录态';
    if (reason === 'invalid_storage_state_json') return '登录态文件无效';
    return reason || '登录态不可用';
  };

  const loadPlatformAccounts = async () => {
    setBusy(true);
    setNotice('');
    try {
      const result = await api.adminPlatformAccounts({ source_key: platformForm.source_key || 'gscloud', include_inactive: true, admin_token: adminToken });
      setPlatformAccounts(result.accounts || []);
      setNotice(`已加载 ${result.accounts?.length || 0} 个平台账号。`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '加载平台账号失败。');
    } finally {
      setBusy(false);
    }
  };

  const addPlatformAccount = async () => {
    if (!platformForm.label.trim()) {
      setNotice('请填写平台账号标签。');
      return;
    }
    setBusy(true);
    setNotice('');
    try {
      await api.upsertAdminPlatformAccount({ ...platformForm, admin_token: adminToken });
      setPlatformForm((prev) => ({ ...prev, username: '', password: '' }));
      setNotice('平台账号已保存。账号密码不会返回到前端；如需要下载，请继续更新登录态。');
      await loadPlatformAccounts();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '保存平台账号失败。');
    } finally {
      setBusy(false);
    }
  };

  const refreshPlatformAccountHealth = async (accountId: string) => {
    setBusy(true);
    setNotice('');
    try {
      const result = await api.adminPlatformAccountHealth(accountId, adminToken);
      setPlatformAccounts((prev) => prev.map((item) => item.account_id === accountId ? { ...item, login_health: result.login_health } : item));
      setNotice(result.login_health?.ok ? '登录态检查通过。' : `登录态不可用：${healthLabel({ account_id: accountId, source_key: 'gscloud', login_health: result.login_health })}`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '检查登录态失败。');
    } finally {
      setBusy(false);
    }
  };

  const startPlatformLogin = async (accountId: string) => {
    setBusy(true);
    setNotice('');
    try {
      const result = await api.startAdminPlatformAccountLogin(accountId, { timeout_seconds: 300, headless: false, admin_token: adminToken });
      setPlatformAccounts((prev) => prev.map((item) => item.account_id === accountId ? result.account : item));
      setNotice(`已打开 GSCloud 登录窗口：${result.login_job?.login_job_id || 'login job'}。请在弹出的浏览器中完成登录，完成后点击“检查登录态”。`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '打开登录窗口失败。');
    } finally {
      setBusy(false);
    }
  };

  const disablePlatformAccount = async (accountId: string) => {
    setBusy(true);
    setNotice('');
    try {
      const result = await api.updateAdminPlatformAccountStatus(accountId, 'disabled', adminToken);
      setPlatformAccounts((prev) => prev.map((item) => item.account_id === accountId ? result.account : item));
      setNotice('平台账号已停用，不会再被下载任务自动选择。');
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '停用平台账号失败。');
    } finally {
      setBusy(false);
    }
  };

  const load = async () => {
    setBusy(true);
    setNotice('');
    try {
      const result = await api.capabilityResources(resourceType, { include_disabled: true, admin_token: adminToken });
      setItems(result.items || []);
      setNotice(`已加载 ${result.items?.length || 0} 条 ${resourceType} 记录。`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '加载能力配置失败。');
    } finally {
      setBusy(false);
    }
  };

  const uploadKnowledge = async (file: File | null) => {
    if (!file) return;
    setBusy(true);
    setNotice('');
    try {
      await api.uploadCapabilityKnowledge({ file, admin_token: adminToken, title: file.name, source: 'admin_upload', version: 'v1', status: 'draft' });
      setNotice('知识文档已上传为 draft。请先检索测试，确认后提交审核并激活。');
      if (resourceType === 'knowledge') await load();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '上传知识文档失败。');
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
      setNotice(error instanceof Error ? error.message : '知识检索测试失败。');
    } finally {
      setBusy(false);
    }
  };

  const updateStatus = async (item: CapabilityResource, status: 'pending_review' | 'active' | 'disabled') => {
    const id = resourceId(item);
    if (!id) return;
    setBusy(true);
    setNotice('');
    try {
      const summary =
        status === 'pending_review'
          ? '前端提交审核'
          : status === 'active'
            ? '前端审核通过并激活'
            : '前端停用';
      await api.updateCapabilityStatus(resourceType, id, status, adminToken, { actor, summary });
      setNotice(status === 'active' ? '已激活为 active，Planner 可按需检索使用。' : status === 'pending_review' ? '已提交审核。' : '已停用。');
      await load();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '更新状态失败。');
    } finally {
      setBusy(false);
    }
  };

  const runSystemReset = async () => {
    if (resetConfirmText.trim() !== expectedResetText) {
      setNotice(`请输入确认文本：${expectedResetText}`);
      return;
    }
    setBusy(true);
    setNotice('');
    try {
      const result = await api.systemReset({ mode: resetMode, confirm_text: resetConfirmText.trim(), admin_token: adminToken });
      const bytes = Number(result.deleted?.bytes || 0);
      const mb = bytes > 0 ? `，释放 ${(bytes / 1024 / 1024).toFixed(1)} MB` : '';
      const accounts = Number(result.preserved?.accounts || 0);
      setNotice(`系统清理完成：删除 ${result.deleted?.files || 0} 个文件${mb}。保留账号 ${accounts} 个。请刷新页面重新加载干净工作区。`);
      setItems([]);
      setSearchHits([]);
      setResetConfirmText('');
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '系统清理失败。');
    } finally {
      setBusy(false);
    }
  };

  const scanStorageCleanup = async () => {
    setBusy(true);
    setNotice('');
    try {
      const result = await api.storageCleanupScan(adminToken);
      const safe = (result.candidates || []).filter((item) => item.safe_to_delete);
      setCleanupCandidates(result.candidates || []);
      setSelectedCleanupIds(safe.map((item) => item.candidate_id));
      setNotice(`扫描完成：发现 ${result.total_candidates || 0} 个可清理候选，预计释放 ${formatBytes(Number(result.total_size_bytes || 0))}。`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '历史数据扫描失败。');
    } finally {
      setBusy(false);
    }
  };

  const runStorageCleanup = async () => {
    if (cleanupConfirmText.trim() !== '删除历史缓存') {
      setNotice('请输入确认文本：删除历史缓存');
      return;
    }
    if (selectedCleanupIds.length === 0) {
      setNotice('没有选择要清理的候选项。');
      return;
    }
    setBusy(true);
    setNotice('');
    try {
      const result = await api.storageCleanupDelete({ candidate_ids: selectedCleanupIds, confirm_text: cleanupConfirmText.trim(), admin_token: adminToken });
      setNotice(`历史清理完成：删除 ${result.deleted_count || 0} 项，释放 ${formatBytes(Number(result.freed_bytes || 0))}。`);
      setCleanupConfirmText('');
      await scanStorageCleanup();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '历史数据清理失败。');
    } finally {
      setBusy(false);
    }
  };

  const loadAvailabilityProfiles = async () => {
    setBusy(true);
    setNotice('');
    try {
      const result = await api.datasetAvailabilityProfiles({ include_inactive: true, admin_token: adminToken });
      setAvailabilityProfiles(result.items || []);
      setNotice(`已加载 ${result.items?.length || 0} 条数据集可用性档案。`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '加载数据集可用性档案失败。');
    } finally {
      setBusy(false);
    }
  };

  const scanAvailabilityProfile = async () => {
    const productId = availabilityProductId.trim();
    if (!productId) {
      setNotice('请先选择或输入 Product Catalog 中的 product_id。');
      return;
    }
    setBusy(true);
    setNotice('');
    try {
      const result = await api.scanDatasetAvailability(productId, {
        scan_method: 'catalog_metadata',
        actor,
        summary: '前端扫描产品可用性',
        admin_token: adminToken
      });
      setAvailabilityProfiles((prev) => [result.item, ...prev.filter((item) => item.product_id !== result.item.product_id)]);
      setNotice('扫描完成：已生成 draft 档案。请核对时间范围、格式和说明后提交审核并激活。');
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '扫描产品可用性失败。');
    } finally {
      setBusy(false);
    }
  };

  const updateAvailabilityStatus = async (productId: string, status: 'pending_review' | 'active' | 'disabled') => {
    setBusy(true);
    setNotice('');
    try {
      const summary =
        status === 'pending_review'
          ? '前端提交数据集可用性审核'
          : status === 'active'
            ? '前端审核通过并激活数据集可用性档案'
            : '前端停用数据集可用性档案';
      const result = await api.updateDatasetAvailabilityStatus(productId, status, adminToken, { actor, summary });
      setAvailabilityProfiles((prev) => prev.map((item) => item.product_id === productId ? result.item : item));
      setNotice(status === 'active' ? '已激活可用性档案，Validator 将按此约束校验下载时间。' : status === 'pending_review' ? '已提交审核。' : '已停用。');
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '更新可用性档案状态失败。');
    } finally {
      setBusy(false);
    }
  };

  const renderResourceItems = () => items.length > 0 && (
    <div className="mt-3 max-h-44 space-y-2 overflow-y-auto">
      {items.map((item) => {
        const id = resourceId(item);
        return (
          <div key={`${id}:${item.version || ''}`} className="rounded-2xl border border-white/30 bg-white/45 px-3 py-2 text-xs dark:border-white/10 dark:bg-white/5">
            <div className="font-bold">{item.title || item.display_name_zh || item.name || id}</div>
            <div className="mt-1 text-slate-500 dark:text-slate-400">{id} / {item.version || 'unversioned'} / {item.status || 'unknown'}</div>
            <div className="mt-2 flex flex-wrap gap-2">
              <button type="button" disabled={busy || item.status === 'pending_review' || item.status === 'active'} onClick={() => updateStatus(item, 'pending_review')} className="rounded-xl border border-slate-200 bg-white/70 px-2 py-1 font-bold text-slate-600 disabled:opacity-40 dark:border-slate-700 dark:bg-slate-950/50 dark:text-slate-300">提交审核</button>
              <button type="button" disabled={busy || item.status === 'active'} onClick={() => updateStatus(item, 'active')} className="rounded-xl bg-emerald-500 px-2 py-1 font-bold text-white disabled:opacity-40">激活</button>
              <button type="button" disabled={busy || item.status === 'disabled'} onClick={() => updateStatus(item, 'disabled')} className="rounded-xl border border-rose-200 bg-rose-50 px-2 py-1 font-bold text-rose-600 disabled:opacity-40 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-300">停用</button>
            </div>
          </div>
        );
      })}
    </div>
  );

  return (
    <div className="mt-4 rounded-[18px] border border-white/30 bg-white/35 p-3 dark:border-white/10 dark:bg-white/5">
      <div className="mb-3">
        <div className="text-sm font-black">知识与能力管理</div>
        <div className="text-xs text-slate-500 dark:text-slate-400">管理员配置 Planner 可检索的知识、工具卡、产品目录和默认资产。</div>
      </div>
      <div className="space-y-2">
        <input
          value={adminToken}
          onChange={(event) => setAdminToken(event.target.value)}
          type="password"
          placeholder="管理员密钥"
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
          <button type="button" onClick={load} disabled={busy} className="glass-button px-4 text-sm font-bold disabled:opacity-50">加载</button>
        </div>
        <label className="block rounded-2xl border border-dashed border-slate-300 bg-white/45 px-3 py-2 text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-950/40 dark:text-slate-300">
          上传知识文档（md / txt / pdf / docx）
          <input type="file" accept=".md,.txt,.pdf,.docx" className="mt-2 block w-full text-xs" onChange={(event) => uploadKnowledge(event.target.files?.[0] || null)} />
        </label>
        <div className="flex gap-2">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Test retrieval query"
            className="min-w-0 flex-1 rounded-2xl border border-slate-200 bg-white/75 px-3 py-2 text-sm outline-none focus:border-cyan-400 dark:border-slate-700 dark:bg-slate-950/70"
          />
          <button type="button" onClick={testSearch} disabled={busy} className="glass-button px-4 text-sm font-bold disabled:opacity-50">测试</button>
        </div>
      </div>
      {notice && <div className="mt-3 rounded-2xl bg-slate-900/5 px-3 py-2 text-xs text-slate-600 dark:bg-white/5 dark:text-slate-300">{notice}</div>}
      {renderResourceItems()}
      <div className="mt-4 rounded-2xl border border-indigo-200 bg-indigo-50/80 p-3 dark:border-indigo-900/60 dark:bg-indigo-950/25">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <div className="text-sm font-black text-indigo-900 dark:text-indigo-100">数据集可用性扫描</div>
            <div className="mt-1 text-xs leading-5 text-indigo-800/80 dark:text-indigo-100/80">
              扫描当前 Product Catalog 与受控产品入口，生成 draft 档案；只有审核激活后才会约束下载时间、格式和可用性。
            </div>
          </div>
          <button type="button" onClick={loadAvailabilityProfiles} disabled={busy} className="rounded-2xl border border-indigo-300 bg-white/80 px-3 py-2 text-xs font-black text-indigo-800 disabled:opacity-45 dark:border-indigo-900/70 dark:bg-slate-950/50 dark:text-indigo-100">加载档案</button>
        </div>
        <div className="mt-3 grid gap-2 md:grid-cols-[1fr_auto_auto]">
          <input
            list="dataset-availability-product-ids"
            value={availabilityProductId}
            onChange={(event) => setAvailabilityProductId(event.target.value)}
            placeholder="product_id，例如 gscloud_ndvi_500m_10day"
            className="rounded-2xl border border-indigo-200 bg-white/80 px-3 py-2 text-xs outline-none focus:border-cyan-400 dark:border-indigo-900/60 dark:bg-slate-950/60"
          />
          <datalist id="dataset-availability-product-ids">
            {DOWNLOAD_PRODUCT_IDS.map((productId) => (
              <option key={productId} value={productId} />
            ))}
          </datalist>
          <button type="button" onClick={scanAvailabilityProfile} disabled={busy} className="rounded-2xl bg-indigo-600 px-3 py-2 text-xs font-black text-white shadow-sm disabled:opacity-45">扫描产品可用性</button>
          <button type="button" onClick={() => setAvailabilityProductId('')} disabled={busy} className="rounded-2xl border border-indigo-200 bg-white/80 px-3 py-2 text-xs font-black text-indigo-700 disabled:opacity-45 dark:border-indigo-900/60 dark:bg-slate-950/60 dark:text-indigo-100">手动输入</button>
        </div>
        {availabilityProfiles.length > 0 && (
          <div className="mt-3 max-h-56 space-y-2 overflow-y-auto">
            {availabilityProfiles.map((profile) => {
              const coverage = profile.temporal_coverage || {};
              const coverageText =
                coverage.start || coverage.end
                  ? `${String(coverage.start || '未知')} 至 ${String(coverage.end || '未知')}`
                  : profile.temporal_requirement === 'none'
                    ? '不适用（无时间维度）'
                    : '待数据源复核';
              return (
                <div key={`${profile.product_id}:${profile.version || ''}`} className="rounded-2xl border border-indigo-200/70 bg-white/65 p-3 text-xs dark:border-indigo-900/50 dark:bg-slate-950/35">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="font-black text-slate-800 dark:text-slate-100">{profile.display_name_zh || profile.product_id}</div>
                      <div className="mt-1 text-slate-500 dark:text-slate-400">
                        {profile.product_id} · {profile.status || 'unknown'} · {profile.verification_method || 'unknown'} · 时间范围：{coverageText}
                      </div>
                      <div className="mt-1 text-slate-500 dark:text-slate-400">
                        分辨率：{(profile.supported_resolutions || []).join(', ') || '未声明'} · 格式：{(profile.supported_formats || []).join(', ') || '未声明'}
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button type="button" disabled={busy || profile.status === 'pending_review' || profile.status === 'active'} onClick={() => updateAvailabilityStatus(profile.product_id, 'pending_review')} className="rounded-xl border border-indigo-200 bg-white/80 px-2.5 py-1.5 font-black text-indigo-700 disabled:opacity-40 dark:border-indigo-900/60 dark:bg-slate-950/60 dark:text-indigo-100">提交审核</button>
                      <button type="button" disabled={busy || profile.status === 'active'} onClick={() => updateAvailabilityStatus(profile.product_id, 'active')} className="rounded-xl bg-emerald-500 px-2.5 py-1.5 font-black text-white disabled:opacity-40">激活</button>
                      <button type="button" disabled={busy || profile.status === 'disabled'} onClick={() => updateAvailabilityStatus(profile.product_id, 'disabled')} className="rounded-xl border border-rose-200 bg-rose-50 px-2.5 py-1.5 font-black text-rose-600 disabled:opacity-40 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-300">停用</button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
      <div className="mt-4 rounded-2xl border border-sky-200 bg-sky-50/80 p-3 dark:border-sky-900/60 dark:bg-sky-950/25">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <div className="text-sm font-black text-sky-900 dark:text-sky-100">平台账号管理</div>
            <div className="mt-1 text-xs leading-5 text-sky-800/80 dark:text-sky-100/80">
              添加 GSCloud 平台账号、更新 Cookie 登录态、检查可用性或停用账号。前端只显示脱敏信息。
            </div>
          </div>
          <button type="button" onClick={loadPlatformAccounts} disabled={busy} className="rounded-2xl border border-sky-300 bg-white/80 px-3 py-2 text-xs font-black text-sky-800 disabled:opacity-45 dark:border-sky-900/70 dark:bg-slate-950/50 dark:text-sky-100">加载账号</button>
        </div>
        <div className="mt-3 grid gap-2 md:grid-cols-3">
          <input
            value={platformForm.label}
            onChange={(event) => setPlatformForm((prev) => ({ ...prev, label: event.target.value }))}
            placeholder="账号标签"
            className="rounded-2xl border border-sky-200 bg-white/80 px-3 py-2 text-xs outline-none focus:border-cyan-400 dark:border-sky-900/60 dark:bg-slate-950/60"
          />
          <input
            value={platformForm.username}
            onChange={(event) => setPlatformForm((prev) => ({ ...prev, username: event.target.value }))}
            placeholder="GSCloud 用户名"
            className="rounded-2xl border border-sky-200 bg-white/80 px-3 py-2 text-xs outline-none focus:border-cyan-400 dark:border-sky-900/60 dark:bg-slate-950/60"
          />
          <input
            value={platformForm.password}
            onChange={(event) => setPlatformForm((prev) => ({ ...prev, password: event.target.value }))}
            type="password"
            placeholder="GSCloud 密码（可留空，只更新额度/标签）"
            className="rounded-2xl border border-sky-200 bg-white/80 px-3 py-2 text-xs outline-none focus:border-cyan-400 dark:border-sky-900/60 dark:bg-slate-950/60"
          />
          <input
            value={platformForm.daily_limit}
            onChange={(event) => setPlatformForm((prev) => ({ ...prev, daily_limit: Number(event.target.value || 0) }))}
            type="number"
            min={1}
            className="rounded-2xl border border-sky-200 bg-white/80 px-3 py-2 text-xs outline-none focus:border-cyan-400 dark:border-sky-900/60 dark:bg-slate-950/60"
            aria-label="每日限额"
          />
          <input
            value={platformForm.monthly_limit}
            onChange={(event) => setPlatformForm((prev) => ({ ...prev, monthly_limit: Number(event.target.value || 0) }))}
            type="number"
            min={1}
            className="rounded-2xl border border-sky-200 bg-white/80 px-3 py-2 text-xs outline-none focus:border-cyan-400 dark:border-sky-900/60 dark:bg-slate-950/60"
            aria-label="每月限额"
          />
          <button type="button" onClick={addPlatformAccount} disabled={busy} className="rounded-2xl bg-sky-600 px-3 py-2 text-xs font-black text-white shadow-sm disabled:opacity-45">添加账号</button>
        </div>
        {platformAccounts.length > 0 && (
          <div className="mt-3 space-y-2">
            {platformAccounts.map((account) => (
              <div key={account.account_id} className="rounded-2xl border border-sky-200/70 bg-white/65 p-3 text-xs dark:border-sky-900/50 dark:bg-slate-950/35">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-black text-slate-800 dark:text-slate-100">{account.label || account.account_id}</div>
                    <div className="mt-1 text-slate-500 dark:text-slate-400">
                      {account.source_key} · {account.username_preview || '未保存用户名'} · {account.status || 'unknown'} · {healthLabel(account)}
                    </div>
                    <div className="mt-1 text-slate-500 dark:text-slate-400">
                      今日 {Number(account.used_today || 0)} / {Number(account.daily_limit || 0)}，本月 {Number(account.used_month || 0)} / {Number(account.monthly_limit || 0)}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button type="button" onClick={() => startPlatformLogin(account.account_id)} disabled={busy || account.status === 'disabled'} className="rounded-xl bg-cyan-600 px-2.5 py-1.5 font-black text-white disabled:opacity-40">更新登录态</button>
                    <button type="button" onClick={() => refreshPlatformAccountHealth(account.account_id)} disabled={busy} className="rounded-xl border border-sky-200 bg-white/80 px-2.5 py-1.5 font-black text-sky-700 disabled:opacity-40 dark:border-sky-900/60 dark:bg-slate-950/60 dark:text-sky-100">检查登录态</button>
                    <button type="button" onClick={() => disablePlatformAccount(account.account_id)} disabled={busy || account.status === 'disabled'} className="rounded-xl border border-rose-200 bg-rose-50 px-2.5 py-1.5 font-black text-rose-600 disabled:opacity-40 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-300">停用账号</button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      {searchHits.length > 0 && (
        <div className="mt-3 space-y-2">
          {searchHits.map((hit) => (
            <div key={hit.id} className="rounded-2xl bg-cyan-500/10 px-3 py-2 text-xs text-slate-700 dark:text-slate-200">{hit.label}</div>
          ))}
        </div>
      )}
      <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50/75 p-3 dark:border-amber-900/60 dark:bg-amber-950/25">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <div className="text-sm font-black text-amber-800 dark:text-amber-100">历史数据清理与迁移</div>
            <div className="mt-1 text-xs leading-5 text-amber-800/80 dark:text-amber-100/80">
              先扫描可安全清理的预览缓存、旧下载后处理缓存、旧时间戳批处理目录，以及未被数据库引用的重复 uploads 文件。
            </div>
          </div>
          <button type="button" onClick={scanStorageCleanup} disabled={busy} className="rounded-2xl border border-amber-300 bg-white/80 px-3 py-2 text-xs font-black text-amber-800 disabled:opacity-45 dark:border-amber-900/70 dark:bg-slate-950/50 dark:text-amber-100">扫描历史数据</button>
        </div>
        {cleanupCandidates.length > 0 && (
          <div className="mt-3 space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-amber-800 dark:text-amber-100">
              <span>已选择 {selectedCleanupIds.length} 项，预计释放 {formatBytes(selectedCleanupBytes)}</span>
              <button
                type="button"
                onClick={() => setSelectedCleanupIds(selectedCleanupIds.length ? [] : cleanupCandidates.filter((item) => item.safe_to_delete).map((item) => item.candidate_id))}
                className="rounded-xl bg-white/70 px-2 py-1 font-bold dark:bg-slate-950/50"
              >
                {selectedCleanupIds.length ? '取消全选' : '选择全部安全项'}
              </button>
            </div>
            <div className="max-h-40 space-y-1 overflow-y-auto rounded-2xl border border-amber-200/70 bg-white/55 p-2 dark:border-amber-900/50 dark:bg-slate-950/30">
              {cleanupCandidates.slice(0, 80).map((item) => (
                <label key={item.candidate_id} className="flex gap-2 rounded-xl px-2 py-1 text-xs text-slate-700 hover:bg-amber-100/70 dark:text-slate-200 dark:hover:bg-amber-950/35">
                  <input
                    type="checkbox"
                    checked={selectedCleanupIds.includes(item.candidate_id)}
                    disabled={!item.safe_to_delete}
                    onChange={(event) => {
                      setSelectedCleanupIds((prev) => event.target.checked ? [...new Set([...prev, item.candidate_id])] : prev.filter((id) => id !== item.candidate_id));
                    }}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="font-bold">{item.category}</span>
                    <span className="ml-2 text-slate-500 dark:text-slate-400">{formatBytes(Number(item.size_bytes || 0))} / {item.file_count || 0} 文件</span>
                    <span className="block truncate text-slate-500 dark:text-slate-400">{item.path}</span>
                  </span>
                </label>
              ))}
            </div>
            <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
              <input
                value={cleanupConfirmText}
                onChange={(event) => setCleanupConfirmText(event.target.value)}
                placeholder="输入“删除历史缓存”确认"
                className="min-w-0 rounded-2xl border border-amber-200 bg-white/80 px-3 py-2 text-sm outline-none focus:border-amber-400 dark:border-amber-900/70 dark:bg-slate-950/70"
              />
              <button
                type="button"
                onClick={runStorageCleanup}
                disabled={busy || cleanupConfirmText.trim() !== '删除历史缓存' || selectedCleanupIds.length === 0}
                className="rounded-2xl bg-amber-600 px-4 py-2 text-sm font-black text-white shadow-sm transition hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-45"
              >
                清理所选项
              </button>
            </div>
          </div>
        )}
      </div>
      <div className="mt-4 rounded-2xl border border-rose-200 bg-rose-50/70 p-3 dark:border-rose-900/60 dark:bg-rose-950/25">
        <div className="text-sm font-black text-rose-700 dark:text-rose-200">危险操作：系统清理</div>
        <div className="mt-1 text-xs leading-5 text-rose-700/80 dark:text-rose-200/80">
          仅管理员可执行。此操作会取消并删除用户会话、上传、下载成果、任务记录、私有知识索引和地图图层；不会删除代码、.env、local_library 或公共能力配置。
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_auto]">
          <select
            value={resetMode}
            onChange={(event) => {
              setResetMode(event.target.value as AdminSystemResetMode);
              setResetConfirmText('');
            }}
            className="min-w-0 rounded-2xl border border-rose-200 bg-white/80 px-3 py-2 text-sm outline-none focus:border-rose-400 dark:border-rose-900/70 dark:bg-slate-950/70"
          >
            <option value="keep_accounts">清除所有用户数据，仅保留账号</option>
            <option value="full_reset">全部删除，恢复最干净状态</option>
          </select>
          <button
            type="button"
            onClick={runSystemReset}
            disabled={busy || resetConfirmText.trim() !== expectedResetText}
            className="rounded-2xl bg-rose-600 px-4 py-2 text-sm font-black text-white shadow-sm transition hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-45"
          >
            执行清理
          </button>
        </div>
        <input
          value={resetConfirmText}
          onChange={(event) => setResetConfirmText(event.target.value)}
          placeholder={`输入“${expectedResetText}”确认`}
          className="mt-2 w-full rounded-2xl border border-rose-200 bg-white/80 px-3 py-2 text-sm outline-none focus:border-rose-400 dark:border-rose-900/70 dark:bg-slate-950/70"
        />
      </div>
    </div>
  );
}
