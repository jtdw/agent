import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

export type ModelMetricDatum = {
  name: string;
  r: number;
  rmse: number;
  nse?: number | null;
  modelResultId?: string;
};

export function ModelMetricChart({ data }: { data: ModelMetricDatum[] }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data}>
        <defs>
          <linearGradient id="barGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#00D4FF" />
            <stop offset="100%" stopColor="#0B5FF4" />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} stroke="rgba(148,163,184,.15)" />
        <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: 'currentColor', fontSize: 12 }} />
        <YAxis axisLine={false} tickLine={false} tick={{ fill: 'currentColor', fontSize: 12 }} />
        <Tooltip
          cursor={{ fill: 'rgba(34,211,238,.08)' }}
          contentStyle={{
            borderRadius: 16,
            border: '1px solid rgba(255,255,255,.35)',
            background: 'rgba(255,255,255,.72)',
            backdropFilter: 'blur(18px)'
          }}
        />
        <Bar dataKey="r" radius={[10, 10, 4, 4]} fill="url(#barGradient)" />
      </BarChart>
    </ResponsiveContainer>
  );
}
