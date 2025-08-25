import { useMemo, useState } from "react";
import { useTokensConsume, calcTokensTotal } from "@/store";
import { formatUtcPlus8 } from "@/store";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  Brush,
} from "recharts";

function monthRange(d = new Date()) {
  const y = d.getUTCFullYear(), m = d.getUTCMonth();
  const from = new Date(Date.UTC(y, m, 1)).toISOString();
  const to   = new Date(Date.UTC(y, m+1, 1)).toISOString();
  return { from, to };
}

/* ===== 公共：颜色分配（按模型名稳定取色） ===== */
const PALETTE = [
  "#3366CC","#DC3912","#FF9900","#109618","#990099",
  "#0099C6","#DD4477","#66AA00","#B82E2E","#316395",
  "#994499","#22AA99","#AAAA11","#6633CC","#E67300",
];
function colorForModel(model) {
  let h = 0;
  const s = String(model || "");
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return PALETTE[h % PALETTE.length];
}
const pad2 = (n) => String(n).padStart(2, "0");
const plus8 = (ms) => ms + 8 * 3600 * 1000;
const fmtTickTsPlus8 = (ts) => {
  const d = new Date(plus8(ts));
  return `${pad2(d.getUTCMonth()+1)}-${pad2(d.getUTCDate())} ${pad2(d.getUTCHours())}:${pad2(d.getUTCMinutes())}`;
};

/* ===== 图1：东八区“按天聚合”折线（可保留/可删） ===== */
const DAY = 24 * 3600 * 1000;
function ymdUtcPlus8(x) {
  const t = (x instanceof Date ? x : new Date(x)).getTime() + 8 * 3600 * 1000;
  const d = new Date(t);
  return `${d.getUTCFullYear()}-${pad2(d.getUTCMonth()+1)}-${pad2(d.getUTCDate())}`;
}
function buildDateKeysUtcPlus8(fromISO, toISO) {
  const fromShift = new Date(new Date(fromISO).getTime() + 8*3600*1000);
  const toShift   = new Date(new Date(toISO).getTime() + 8*3600*1000);
  let t = Date.UTC(fromShift.getUTCFullYear(), fromShift.getUTCMonth(), fromShift.getUTCDate());
  const tEnd = Date.UTC(toShift.getUTCFullYear(), toShift.getUTCMonth(), toShift.getUTCDate());
  const keys = [];
  for (; t < tEnd; t += DAY) {
    const d = new Date(t);
    keys.push(`${d.getUTCFullYear()}-${pad2(d.getUTCMonth()+1)}-${pad2(d.getUTCDate())}`);
  }
  return keys;
}
function buildDailySeriesUtcPlus8(records, fromISO, toISO) {
  const dateKeys = buildDateKeysUtcPlus8(fromISO, toISO);
  const models = Array.from(new Set((records || []).map(r => r.model).filter(Boolean)));
  const map = {};
  dateKeys.forEach(d => {
    map[d] = { date: d };
    models.forEach(m => { map[d][m] = 0; });
  });
  (records || []).forEach(r => {
    const dKey = ymdUtcPlus8(r.created);
    const m = r.model || "unknown";
    const v = Number(r.total_tokens || 0);
    if (!map[dKey]) return;
    if (!(m in map[dKey])) map[dKey][m] = 0;
    map[dKey][m] += v;
  });
  return { data: dateKeys.map(d => map[d]), models };
}

/* ===== 图2：逐笔记录时序折线（按精确时间，东八区显示） ===== */
function buildEventSeries(records) {
  // 模型集合
  const models = Array.from(new Set((records || []).map(r => r.model).filter(Boolean)));

  // 将每条记录映射为一个点：仅该模型字段为值，其它模型字段为 null（避免 0 连线）
  const points = (records || [])
    .map(r => {
      const ts = new Date(r.created).getTime(); // 用 UTC 时间戳作为横轴
      const row = { ts, label: formatUtcPlus8(r.created) };
      const m = r.model || "unknown";
      const v = Number(r.total_tokens || 0);
      models.forEach(mm => { row[mm] = null; });
      row[m] = v;
      return row;
    })
    .sort((a, b) => a.ts - b.ts);

  return { data: points, models };
}

export default function TokensScreen() {
  const [range, setRange] = useState(() => monthRange());
  const { data = [], isLoading, isError, error, refetch } = useTokensConsume(range);
  const total = useMemo(() => calcTokensTotal(data), [data]);

  // 图1：日聚合
  const daily = useMemo(
    () => buildDailySeriesUtcPlus8(data, range.from, range.to),
    [data, range.from, range.to]
  );

  // 图2：逐笔记录
  const detailed = useMemo(
    () => buildEventSeries(data),
    [data]
  );

  const fmtNumber = (n) => (Number(n) || 0).toLocaleString();

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-bold">Tokens 消费</h2>
        <div className="flex items-center gap-2 text-sm">
          <button className="px-2 py-1 border rounded" onClick={() => setRange(monthRange(new Date()))}>本月</button>
          <button className="px-2 py-1 border rounded" onClick={() => { const d = new Date(); d.setUTCMonth(d.getUTCMonth()-1); setRange(monthRange(d)); }}>上月</button>
          <button className="px-2 py-1 border rounded" onClick={() => refetch()}>刷新</button>
        </div>
      </div>

      <div className="mb-3 text-sm text-muted-foreground">
        时间窗：{new Date(range.from).toISOString().slice(0,10)} ~ {new Date(range.to).toISOString().slice(0,10)}
      </div>

      {isLoading && <div>加载中…</div>}
      {isError && <div className="text-red-500">加载失败：{String(error?.message || error)}</div>}

      {!isLoading && !isError && (
        <>
          <div className="mb-4 text-lg">
            合计：<b>{total.toLocaleString()}</b> tokens
          </div>

          {/* ===== 图1：东八区按天汇总（如不需要可删除此块） ===== */}
          {data.length > 0 && (
            <div className="h-72 mb-6 border rounded p-3 bg-white">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={daily.data} margin={{ top: 10, right: 20, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" tick={{ fontSize: 12 }} minTickGap={20} />
                  <YAxis tickFormatter={fmtNumber} tick={{ fontSize: 12 }} width={80} />
                  <Tooltip formatter={(v) => fmtNumber(v)} labelFormatter={(l) => `日期（UTC+8）：${l}`} />
                  <Legend />
                  {daily.models.map((m) => (
                    <Line
                      key={m}
                      type="monotone"
                      dataKey={m}
                      stroke={colorForModel(m)}
                      dot={false}
                      strokeWidth={2}
                      isAnimationActive={false}
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* ===== 图2：逐笔记录时序折线（横轴=精确时间，显示东八区） ===== */}
          {data.length > 0 ? (
            <div className="h-96 mb-6 border rounded p-3 bg-white">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={detailed.data} margin={{ top: 10, right: 20, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis
                    dataKey="ts"
                    type="number"
                    domain={["auto", "auto"]}
                    tickFormatter={fmtTickTsPlus8}
                    tick={{ fontSize: 12 }}
                    minTickGap={20}
                  />
                  <YAxis tickFormatter={fmtNumber} tick={{ fontSize: 12 }} width={80} />
                  <Tooltip
                    formatter={(v, name) => [fmtNumber(v), name]}
                    labelFormatter={(ts) => `时间（UTC+8）：${formatUtcPlus8(new Date(ts))}`}
                  />
                  <Legend />
                  {detailed.models.map((m) => (
                    <Line
                      key={m}
                      type="monotone"
                      dataKey={m}
                      stroke={colorForModel(m)}
                      dot={{ r: 2 }}
                      strokeWidth={2}
                      connectNulls={false}   // 碰到 null 不中断其它模型的线
                      isAnimationActive={false}
                    />
                  ))}
                  <Brush
                    dataKey="ts"
                    travellerWidth={8}
                    height={24}
                    tickFormatter={fmtTickTsPlus8}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="mb-6 px-3 py-3 text-center text-sm text-muted-foreground border rounded bg-white">
              暂无可绘制的数据
            </div>
          )}

          {/* 原表格 */}
          <div className="border rounded overflow-hidden">
            <div className="grid grid-cols-4 font-semibold bg-gray-50 px-3 py-2 border-b">
              <div>时间</div>
              <div>用途</div>
              <div>模型</div>
              <div className="text-right">Total</div>
            </div>
            {data.map((it) => (
              <div key={it.id} className="grid grid-cols-4 px-3 py-2 border-b">
                <div>{formatUtcPlus8(it.created)}</div>
                <div className="truncate">{it.purpose}</div>
                <div className="truncate">{it.model}</div>
                <div className="text-right">{Number(it.total_tokens || 0).toLocaleString()}</div>
              </div>
            ))}
            {data.length === 0 && <div className="px-3 py-6 text-center text-sm text-muted-foreground">暂无记录</div>}
          </div>
        </>
      )}
    </div>
  );
}
