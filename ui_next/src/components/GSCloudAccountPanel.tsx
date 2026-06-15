import { CheckCircle2, Cloud, LogIn, LogOut, RefreshCcw, ShieldCheck } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, DataSourceAccountStatus } from '@/lib/api';
import { cn } from '@/lib/cn';

export function GSCloudAccountPanel({
  enabled,
  pendingJobId = '',
  onLoginComplete
}: {
  enabled: boolean;
  pendingJobId?: string;
  onLoginComplete?: (jobId: string) => void;
}) {
  const [status, setStatus] = useState<DataSourceAccountStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const pollRef = useRef<number | null>(null);

  const stopPolling = () => {
    if (pollRef.current !== null) window.clearInterval(pollRef.current);
    pollRef.current = null;
  };

  const refresh = useCallback(async () => {
    if (!enabled) return;
    try {
      setStatus(await api.gscloudStatus());
    } catch (cause) {
      setNotice(cause instanceof Error ? cause.message : '账号状态读取失败');
    }
  }, [enabled]);

  useEffect(() => {
    refresh();
    return stopPolling;
  }, [refresh]);

  const startLogin = async () => {
    setBusy(true);
    setNotice('');
    stopPolling();
    try {
      const started = await api.startGSCloudLogin();
      setNotice(started.user_message || '已打开登录窗口，请在官方页面完成登录。');
      const check = async () => {
        const result = await api.completeGSCloudLogin(started.login_session_id);
        setStatus(result);
        if (result.logged_in) {
          stopPolling();
          setBusy(false);
          setNotice('已检测到账号登录成功。');
          onLoginComplete?.(pendingJobId);
        } else if (!result.pending && result.login_state === 'FAILED') {
          stopPolling();
          setBusy(false);
          setNotice(result.user_message || '登录未完成，请重新登录。');
        }
        return result;
      };
      const initial = await check();
      if (!initial.logged_in && initial.pending && !pollRef.current) {
        pollRef.current = window.setInterval(() => check().catch(() => {}), started.poll_interval_ms || 2000);
      }
    } catch (cause) {
      setBusy(false);
      setNotice(cause instanceof Error ? cause.message : '无法启动登录窗口');
    }
  };

  const logout = async () => {
    setBusy(true);
    try {
      setStatus(await api.logoutGSCloud());
      setNotice('已退出地理空间数据云账号。');
    } catch (cause) {
      setNotice(cause instanceof Error ? cause.message : '退出登录失败');
    } finally {
      setBusy(false);
    }
  };

  const loggedIn = Boolean(status?.logged_in);
  return (
    <section data-testid="gscloud-account-panel" className="rounded-[20px] border border-white/35 bg-white/45 p-4 dark:border-white/10 dark:bg-white/5">
      <div className="flex items-start gap-3">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-2xl bg-cyan-glow/10 text-cyan-glow"><Cloud size={19} /></div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-black">地理空间数据云账号</h3>
            <span className={cn('rounded-full px-2 py-0.5 text-[11px] font-black', loggedIn ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300' : 'bg-amber-500/15 text-amber-700 dark:text-amber-300')}>
              {loggedIn ? '已登录' : '未登录'}
            </span>
          </div>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{status?.user_message || '用于 DEM、遥感影像等受保护数据下载。'}</p>
        </div>
      </div>
      <div className="mt-3 flex items-start gap-2 rounded-2xl bg-slate-900/5 p-3 text-xs text-slate-600 dark:bg-white/5 dark:text-slate-300">
        <ShieldCheck size={15} className="mt-0.5 shrink-0" />
        <span>账号密码不会保存在聊天记录中。请仅在地理空间数据云官方登录页输入密码。</span>
      </div>
      {notice && <p className="mt-3 text-xs font-semibold text-slate-600 dark:text-slate-300">{notice}</p>}
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" onClick={startLogin} disabled={!enabled || busy} className="glass-button inline-flex items-center gap-2 px-3 py-2 text-sm font-black">
          {loggedIn ? <RefreshCcw size={15} /> : <LogIn size={15} />}{loggedIn ? '重新登录' : '登录'}
        </button>
        {loggedIn && (
          <button type="button" onClick={logout} disabled={busy} className="glass-button inline-flex items-center gap-2 px-3 py-2 text-sm font-black text-coral">
            <LogOut size={15} />退出登录
          </button>
        )}
        {loggedIn && <span className="inline-flex items-center gap-1 text-xs font-bold text-emerald-600 dark:text-emerald-300"><CheckCircle2 size={14} />登录态可用</span>}
      </div>
    </section>
  );
}
