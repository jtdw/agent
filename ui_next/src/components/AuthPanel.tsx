import { useEffect, useMemo, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Check, Crown, LockKeyhole, LogIn, Mail, Rocket, ShieldCheck, Sparkles, UserPlus, X } from 'lucide-react';
import { api, CommercialUser, PaidPlan } from '@/lib/api';
import { GlassCard } from './GlassCard';
import { cn } from '@/lib/cn';

const USER_KEY = 'gis-agent-auth-user';
const LEGACY_SESSION_KEY = 'gis-agent-auth-session';

type PlanMeta = {
  key: 'basic' | 'pro' | 'team';
  label: string;
  subtitle: string;
  price: string;
  quota: string;
  popular?: boolean;
  features: string[];
};

const PLAN_META: Record<'basic' | 'pro' | 'team', PlanMeta> = {
  basic: {
    key: 'basic',
    label: 'BASIC',
    subtitle: '默认账号',
    price: '免费',
    quota: '平台额度 0',
    features: ['可使用自己的地理空间数据云账号', '支持基础数据下载任务登记', '适合普通课程实验与本地数据处理']
  },
  pro: {
    key: 'pro',
    label: 'PRO',
    subtitle: '个人高级版',
    price: '¥20 / 月',
    quota: '平台额度 50 次/月',
    popular: true,
    features: ['更高数据下载额度', '自动提交地理空间数据云下载任务', '适合单人论文与课程项目']
  },
  team: {
    key: 'team',
    label: 'TEAM',
    subtitle: '团队协作版',
    price: '¥59 / 月',
    quota: '平台额度 300 次/月',
    features: ['更高数据下载额度', '适合小组项目与批量区域任务', '后续可扩展团队成员管理']
  }
};

export function readStoredUser(): CommercialUser | null {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function writeStoredUser(user: CommercialUser) {
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

function normalizePlan(plan?: string): 'basic' | 'pro' | 'team' {
  if (plan === 'pro' || plan === 'team') return plan;
  return 'basic';
}

function formatExpire(value?: string) {
  if (!value) return '长期有效';
  return String(value).slice(0, 10);
}

function PlanBadge({ plan, onClick }: { plan: string | undefined; onClick?: () => void }) {
  const normalized = normalizePlan(plan);
  const styles = {
    basic: 'border-slate-200/70 bg-white/60 text-slate-700 dark:border-white/10 dark:bg-white/5 dark:text-slate-200',
    pro: 'border-cyan-glow/30 bg-cyan-glow/15 text-ocean dark:text-cyan-glow',
    team: 'border-violet-300/40 bg-violet-400/15 text-violet-700 dark:text-violet-200'
  }[normalized];
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-black tracking-wide shadow-sm transition',
        onClick && 'cursor-pointer hover:-translate-y-0.5 hover:shadow-glow focus:outline-none focus:ring-2 focus:ring-cyan-glow/45',
        styles
      )}
      title="查看或调整套餐"
    >
      {normalized === 'basic' ? <ShieldCheck size={12} strokeWidth={1.7} /> : normalized === 'pro' ? <Rocket size={12} strokeWidth={1.7} /> : <Crown size={12} strokeWidth={1.7} />}
      {PLAN_META[normalized].label}
    </button>
  );
}

function UpgradeModal({ user, open, onClose, onUpgraded }: { user: CommercialUser; open: boolean; onClose: () => void; onUpgraded: (user: CommercialUser) => void }) {
  const [busyPlan, setBusyPlan] = useState<PaidPlan | ''>('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const currentPlan = normalizePlan(user.plan);

  const pay = async (plan: PaidPlan) => {
    setBusyPlan(plan);
    setError('');
    setSuccess('');
    try {
      const r = await api.pay(user.user_id, plan);
      onUpgraded(r.user);
      writeStoredUser(r.user);
      setSuccess(`已升级为 ${PLAN_META[normalizePlan(r.user.plan)].label}，下次登录仍会保持该状态。`);
      window.setTimeout(onClose, 850);
    } catch (e) {
      setError(e instanceof Error ? e.message : '支付失败');
    } finally {
      setBusyPlan('');
    }
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-[95] grid place-items-center bg-slate-950/25 p-4 backdrop-blur-md dark:bg-black/55" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 8 }}
            transition={{ type: 'spring', stiffness: 360, damping: 32 }}
            className="glass-panel w-full max-w-3xl overflow-hidden rounded-[30px] p-0"
          >
            <div className="relative border-b border-white/30 px-6 py-5 dark:border-white/10">
              <button onClick={onClose} className="glass-button absolute right-4 top-4 h-9 w-9 rounded-2xl p-0"><X size={16} strokeWidth={1.6} /></button>
              <div className="flex items-center gap-3">
                <div className="grid h-12 w-12 place-items-center rounded-2xl bg-gradient-to-br from-ocean to-cyan-glow text-white shadow-glow">
                  <Crown size={22} strokeWidth={1.5} />
                </div>
                <div>
                  <h2 className="text-xl font-black tracking-tight text-slate-950 dark:text-slate-50">升级套餐</h2>
                  <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">当前账号为 <b>{PLAN_META[currentPlan].label}</b>。升级后状态写入商业数据库，下次登录自动同步。</p>
                </div>
              </div>
            </div>

            <div className="grid gap-4 p-5 md:grid-cols-2">
              {(['pro', 'team'] as const).map((plan) => {
                const item = PLAN_META[plan];
                const isCurrent = currentPlan === plan;
                return (
                  <motion.div
                    key={plan}
                    whileHover={{ y: -3, scale: 1.01 }}
                    className={cn(
                      'relative overflow-hidden rounded-[26px] border p-5 transition',
                      item.popular ? 'border-cyan-glow/45 bg-cyan-glow/10 shadow-glow' : 'border-white/40 bg-white/35 dark:border-white/10 dark:bg-white/5'
                    )}
                  >
                    {item.popular && <div className="absolute right-4 top-4 rounded-full bg-gradient-to-r from-ocean to-cyan-glow px-2.5 py-1 text-[11px] font-black text-white shadow-glow">推荐</div>}
                    <div className="flex items-center gap-2">
                      <div className="grid h-10 w-10 place-items-center rounded-2xl bg-white/70 text-ocean shadow-sm dark:bg-white/10 dark:text-cyan-glow">
                        {plan === 'pro' ? <Rocket size={18} strokeWidth={1.5} /> : <Crown size={18} strokeWidth={1.5} />}
                      </div>
                      <div>
                        <div className="text-lg font-black tracking-tight">{item.label}</div>
                        <div className="text-xs text-slate-500 dark:text-slate-400">{item.subtitle}</div>
                      </div>
                    </div>
                    <div className="mt-5 flex items-end gap-2">
                      <span className="text-3xl font-black tracking-tight">{item.price}</span>
                      <span className="pb-1 text-xs text-slate-500 dark:text-slate-400">模拟支付</span>
                    </div>
                    <div className="mt-2 rounded-2xl border border-white/40 bg-white/45 px-3 py-2 text-sm font-bold text-slate-700 dark:border-white/10 dark:bg-slate-950/20 dark:text-slate-200">{item.quota}</div>
                    <div className="mt-4 space-y-2">
                      {item.features.map((f) => (
                        <div key={f} className="flex gap-2 text-sm leading-5 text-slate-600 dark:text-slate-300">
                          <Check className="mt-0.5 shrink-0 text-cyan-glow" size={15} strokeWidth={1.8} />
                          <span>{f}</span>
                        </div>
                      ))}
                    </div>
                    <button
                      disabled={Boolean(busyPlan) || isCurrent}
                      onClick={() => pay(plan)}
                      className={cn('primary-button mt-5 w-full gap-2 disabled:cursor-not-allowed disabled:opacity-55', plan === 'team' && 'bg-none')}
                      style={plan === 'team' ? { background: 'linear-gradient(135deg, #7c3aed, #22d3ee)' } : undefined}
                    >
                      {isCurrent ? '当前套餐' : busyPlan === plan ? '处理中...' : currentPlan === 'pro' && plan === 'team' ? '升级到 TEAM' : `升级到 ${item.label}`}
                    </button>
                  </motion.div>
                );
              })}
            </div>
            {(error || success) && (
              <div className="px-5 pb-5">
                <div className={cn('rounded-2xl border px-4 py-3 text-sm font-semibold', error ? 'border-coral/25 bg-coral/10 text-coral' : 'border-emerald-300/30 bg-emerald-400/10 text-emerald-600 dark:text-emerald-300')}>
                  {error || success}
                </div>
              </div>
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export function AuthPanel({ user, setUser }: { user: CommercialUser | null; setUser: (user: CommercialUser | null) => void }) {
  const [open, setOpen] = useState(false);
  const [upgradeOpen, setUpgradeOpen] = useState(false);
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    localStorage.removeItem(LEGACY_SESSION_KEY);
    const saved = readStoredUser();
    if (saved) setUser(saved);
    api.me()
      .then((r) => {
        setUser(r.user);
        writeStoredUser(r.user);
      })
      .catch(() => {
        localStorage.removeItem(USER_KEY);
        setUser(null);
      });
  }, [setUser]);

  const submit = async () => {
    setBusy(true);
    setError('');
    try {
      const session = mode === 'login' ? await api.login(email, password) : await api.register(email, password);
      writeStoredUser(session.user);
      setUser(session.user);
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : '操作失败');
    } finally {
      setBusy(false);
    }
  };

  const plan = normalizePlan(user?.plan);
  const quota = Math.max(0, Number(user?.platform_monthly_quota || 0) - Number(user?.platform_monthly_used || 0));
  const planHint = useMemo(() => {
    if (!user) return '';
    if (plan === 'basic') return '默认 BASIC，可使用基础数据处理与任务登记。';
    if (plan === 'pro') return `PRO 有效期至 ${formatExpire(user.plan_expires_at)}；剩余下载额度 ${quota}。`;
    return `TEAM 有效期至 ${formatExpire(user.plan_expires_at)}；剩余下载额度 ${quota}。`;
  }, [user, plan, quota]);

  if (user) {
    return (
      <>
        <GlassCard className="p-3.5">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-ocean to-cyan-glow text-white shadow-glow">
              <Crown size={18} strokeWidth={1.5} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex min-w-0 items-center gap-2">
                <div className="truncate text-sm font-black text-slate-950 dark:text-slate-50">{user.email}</div>
                <PlanBadge plan={user.plan} onClick={() => setUpgradeOpen(true)} />
              </div>
              <div className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">{planHint}</div>
            </div>
            <button className="glass-button px-2 py-1 text-xs" onClick={() => { api.logout().catch(() => undefined); localStorage.removeItem(USER_KEY); localStorage.removeItem(LEGACY_SESSION_KEY); setUser(null); }}>退出</button>
          </div>
        </GlassCard>
        <UpgradeModal user={user} open={upgradeOpen} onClose={() => setUpgradeOpen(false)} onUpgraded={setUser} />
      </>
    );
  }

  return (
    <>
      <button onClick={() => setOpen(true)} className="primary-button w-full gap-2">
        <LogIn size={16} strokeWidth={1.5} /> 登录 / 注册账号
      </button>
      <AnimatePresence>
        {open && (
          <motion.div className="fixed inset-0 z-[90] grid place-items-center bg-slate-950/20 p-4 backdrop-blur-md dark:bg-black/50" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <motion.div initial={{ opacity: 0, scale: 0.95, y: 10 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.96, y: 8 }} transition={{ duration: 0.16 }} className="glass-panel w-full max-w-md rounded-[28px] p-6">
              <div className="mb-6 flex items-center gap-3">
                <div className="grid h-12 w-12 place-items-center rounded-2xl bg-gradient-to-br from-ocean to-cyan-glow text-white shadow-glow">
                  <Sparkles size={22} strokeWidth={1.5} />
                </div>
                <div>
                  <h2 className="text-xl font-black tracking-tight">{mode === 'login' ? '登录 GIS 智能体' : '创建 BASIC 账号'}</h2>
                  <p className="text-sm text-slate-500 dark:text-slate-400">新注册账号默认为 BASIC，升级后可获得更多下载额度。</p>
                </div>
              </div>
              <div className="space-y-3">
                <label className="relative block">
                  <Mail className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} strokeWidth={1.5} />
                  <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="邮箱账号" className="input-glass w-full pl-10" />
                </label>
                <label className="relative block">
                  <LockKeyhole className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} strokeWidth={1.5} />
                  <input value={password} onChange={(e) => setPassword(e.target.value)} placeholder="密码" type="password" className="input-glass w-full pl-10" />
                </label>
              </div>
              {error && <div className="mt-3 rounded-xl border border-coral/20 bg-coral/10 px-3 py-2 text-sm text-coral">{error}</div>}
              <button onClick={submit} disabled={busy || !email || !password} className="primary-button mt-5 w-full gap-2 disabled:opacity-50">
                {mode === 'login' ? <LogIn size={16} /> : <UserPlus size={16} />} {busy ? '处理中...' : mode === 'login' ? '登录' : '注册 BASIC 账号'}
              </button>
              <button onClick={() => setMode(mode === 'login' ? 'register' : 'login')} className="mt-4 w-full text-sm font-semibold text-slate-500 transition hover:text-ocean dark:text-slate-400">
                {mode === 'login' ? '没有账号？立即注册' : '已有账号？返回登录'}
              </button>
              <button onClick={() => setOpen(false)} className="mt-2 w-full text-xs text-slate-400 hover:text-slate-600">关闭</button>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
