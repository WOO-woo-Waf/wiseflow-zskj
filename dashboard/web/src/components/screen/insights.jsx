import { useEffect, useMemo, useState } from "react";
import { useQueries, useMutation, useQueryClient } from "@tanstack/react-query";
import { Files } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { ArticleList } from "@/components/article-list";
import { Button } from "@/components/ui/button";
import { Toaster } from "@/components/ui/toaster";
import { useToast } from "@/components/ui/use-toast";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";

import {
  getInsights,
  getInsightDates,
  useClientStore,
  unlinkArticle,
  more,
  useTags,
} from "@/store";

/** ---------- 工具 ---------- */
function normalizeTagIds(tagField) {
  if (tagField == null) return [];
  if (Array.isArray(tagField)) return tagField.filter(Boolean).map(String);
  return [String(tagField)];
}

function formatYMD(date, tz = "America/Los_Angeles") {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

function enumerateDates(startYmd, endYmd) {
  if (!startYmd || !endYmd) return [];
  const start = new Date(`${startYmd}T00:00:00`);
  const end = new Date(`${endYmd}T00:00:00`);
  if (isNaN(start) || isNaN(end) || start > end) return [];
  const days = [];
  for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
    days.push(formatYMD(d));
  }
  return days;
}

/** ---------- 多选日期控件（保留） ---------- */
function DateMultiPicker({ dates, selected, onChange }) {
  function toggle(d, checked) {
    const next = checked
      ? Array.from(new Set([...selected, d]))
      : selected.filter((x) => x !== d);
    onChange(next);
  }
  return (
    <div className="flex flex-wrap gap-2">
      {dates.map((d) => (
        <label key={d} className="flex items-center gap-1 text-sm border rounded px-2 py-1 cursor-pointer">
          <input type="checkbox" checked={selected.includes(d)} onChange={(e) => toggle(d, e.target.checked)} />
          {d}
        </label>
      ))}
    </div>
  );
}

/** ---------- 并发拉取并合并 ---------- */
function useInsightsMulti(selectedDates) {
  const queries = useQueries({
    queries: (selectedDates || []).map((d) => ({
      queryKey: ["insights", d],
      queryFn: async () => {
        try {
          return await getInsights(d);
        } catch (err) {
          // 兼容 PocketBase auto-cancel：返回空即可
          if (err?.isAbort || err?.status === 0) return [];
          throw err;
        }
      },
      enabled: !!d,
      staleTime: 60_000,
    })),
  });

  const isLoading = queries.some((q) => q.isLoading);
  const isError = queries.some((q) => q.isError);
  const errorObj = queries.find((q) => q.error)?.error;

  const data = useMemo(() => {
    const list = queries.map((q) => (Array.isArray(q.data) ? q.data : [])).flat();
    return list.sort((a, b) => (a.created > b.created ? -1 : 1));
  }, [JSON.stringify(queries.map((q) => q.data))]);

  return { data, isLoading, isError, error: errorObj };
}

/** ---------- 列表 ---------- */
function List({ insights, selected, selectedIds, onToggleSelect, onOpen, onDelete, onMore, error, tagIdToName }) {
  function change(value) {
    if (value) onOpen(value);
  }
  function unlink(article_id) {
    if (!selected) return;
    onDelete(selected, article_id);
  }

  return (
    <Accordion type="single" collapsible onValueChange={change} className="w-full">
      {insights.map((insight, i) => {
        const tagNames = normalizeTagIds(insight.tag).map((id) => tagIdToName.get(id) || id);
        return (
          <AccordionItem value={insight.id} key={insight.id || i}>
            <AccordionTrigger className="hover:no-underline">
              <div className="px-4 py-2 cursor-pointer flex items-center gap-2 overflow-hidden">
                <input
                  type="checkbox"
                  checked={selectedIds.includes(insight.id)}
                  onClick={(e) => e.stopPropagation()}
                  onChange={(e) => {
                    e.stopPropagation();
                    onToggleSelect(insight.id, e.target.checked);
                  }}
                />
                {selected === insight.id && <div className="-ml-4 w-2 h-2 bg-green-400 rounded-full" />}
                <div className="truncate text-left flex-1">
                  <p className={"truncate text-wrap " + (selected === insight.id ? "font-bold" : "font-normal")}>
                    {insight.content}
                  </p>
                  {tagNames.length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {tagNames.map((name) => (
                        <span key={name} className="text-[11px] px-2 py-[2px] rounded-full bg-gray-100 text-gray-600 border">
                          {name}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <div className="flex items-center justify-center gap-1">
                  <Files className="h-4 w-4 text-slate-400" />
                  <span className="text-slate-400 text-sm leading-none">x {insight.expand?.articles?.length ?? 0}</span>
                </div>
              </div>
            </AccordionTrigger>
            <AccordionContent className="px-4">
              <ArticleList data={insight.expand?.articles ?? []} showActions={true} onDelete={unlink} />
              {error && <p className="text-red-500 my-4">{error.message}</p>}
            </AccordionContent>
          </AccordionItem>
        );
      })}
    </Accordion>
  );
}

/** ---------- 主页面（选择版） ---------- */
export default function InsightsScreen() {
  const [selectedIds, setSelectedIds] = useState([]);
  const [selectedDates, setSelectedDates] = useState([]);
  const selectedInsight = useClientStore((s) => s.selectedInsight);
  const selectInsight = useClientStore((s) => s.selectInsight);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  // 所有可选日期
  const [allDates, setAllDates] = useState([]);
  useEffect(() => {
    getInsightDates().then((ds) => {
      setAllDates(ds || []);
      if ((ds || []).length && selectedDates.length === 0) setSelectedDates([ds[0]]);
    });
  }, []);

  // 数据
  const { data, isLoading, error } = useInsightsMulti(selectedDates);

  // 标签
  const tagsQuery = useTags();
  const tagIdToName = useMemo(() => {
    const map = new Map();
    (tagsQuery.data || []).forEach((t) => map.set(String(t.id), String(t.name ?? t.id)));
    return map;
  }, [tagsQuery.data]);

  const [selectedTagIds, setSelectedTagIds] = useState([]);
  const allTagItems = useMemo(() => {
    const items = (tagsQuery.data || []).map((t) => ({ id: String(t.id), name: String(t.name ?? t.id) }));
    return items.sort((a, b) => a.name.localeCompare(b.name, "zh-Hans-CN"));
  }, [tagsQuery.data]);

  // 日期范围
  const [rangeStart, setRangeStart] = useState("");
  const [rangeEnd, setRangeEnd] = useState("");
  function applyRange() {
    const range = enumerateDates(rangeStart, rangeEnd);
    if (!range.length) {
      toast({ title: "时间范围无效", description: "请检查开始和结束日期", variant: "destructive" });
      return;
    }
    const merged = Array.from(new Set([...selectedDates, ...range])).sort().reverse();
    setSelectedDates(merged);
  }

  // 切换日期时清空选择
  useEffect(() => {
    selectInsight(null);
    setSelectedIds([]);
  }, [JSON.stringify(selectedDates)]);

  // 勾选切换
  function onToggleSelect(id, checked) {
    setSelectedIds((prev) => (checked ? (prev.includes(id) ? prev : [...prev, id]) : prev.filter((x) => x !== id)));
  }

  // 删除文章 & 更多
  function invalidate() {
    selectedDates.forEach((d) => queryClient.invalidateQueries({ queryKey: ["insights", d] }));
  }

  const mutUnlink = useMutation({
    mutationFn: (params) => {
      if (params && selectedInsight) {
        const insight = data.find((i) => i.id === selectedInsight);
        if (insight && (insight.expand?.articles?.length ?? 0) === 1) {
          throw new Error("不能删除最后一篇文章");
        }
      }
      return unlinkArticle(params);
    },
    onSuccess: invalidate,
    onError: (e) => {
      toast({ variant: "destructive", title: "出错啦！", description: e?.message || "操作失败" });
    },
  });

  const mutMore = useMutation({
    mutationFn: (params) => more(params),
    onSuccess: invalidate,
    onError: (e) => {
      toast({ variant: "destructive", title: "出错啦！", description: e?.message || "加载失败" });
    },
  });

  // 过滤（按标签）
  const filteredData = useMemo(() => {
    if (!selectedTagIds.length) return data || [];
    return (data || []).filter((ins) => {
      const ids = normalizeTagIds(ins.tag);
      return ids.some((id) => selectedTagIds.includes(String(id)));
    });
  }, [data, selectedTagIds]);

  // 全选 / 反选 / 清空（针对可见列表）
  function selectAllVisible() {
    setSelectedIds((filteredData || []).map((i) => i.id));
  }

  function invertSelection() {
    setSelectedIds((prev) => {
      const prevSet = new Set(prev);
      const result = [];
      (filteredData || []).forEach((i) => {
        if (!prevSet.has(i.id)) result.push(i.id);
      });
      return result;
    });
  }

  function clearSelection() {
    setSelectedIds([]);
  }

  // 快捷日期（只改变日期集合，不触发生成）
  function quickToday() {
    const today = formatYMD(new Date());
    if ((allDates || []).includes(today)) {
      setSelectedDates([today]);
    } else {
      toast({ title: "今天没有内容", description: "已保持当前选择", variant: "destructive" });
    }
  }

  function quickLast7Days() {
    const end = new Date();
    const recentDates = [];
    for (let i = 0; i < 7; i++) {
      const d = new Date(end);
      d.setDate(end.getDate() - i);
      recentDates.push(formatYMD(d));
    }
    const available = allDates || [];
    const inWindow = recentDates.filter((d) => available.includes(d));
    const finalDates = inWindow.length > 0 ? inWindow : available.slice(0, 7);
    if (!finalDates.length) {
      toast({ title: "暂无数据", description: "近7天以及历史均无可用日期", variant: "destructive" });
      return;
    }
    setSelectedDates(Array.from(new Set(finalDates)));
  }

  // 统一生成（固定函数）
  function handleGenerate() {
    if (!selectedIds.length) {
      toast({ title: "未选择洞见", description: "请先勾选至少一条洞见", variant: "destructive" });
      return;
    }
    const ids = selectedIds.slice();
    const anchor = ids[0];
    const qs = `?ids=${encodeURIComponent(ids.join(","))}`;
    navigate(`/report/${anchor}${qs}`);
  }
  // 生成“勾选报告”（跨天）
  function reportSelected() {
    if (!selectedIds.length) {
      toast({ title: "请选择洞见", description: "请先勾选至少一条洞见", variant: "destructive" });
      return;
    }
    const anchor = selectedIds[0];
    const qs = `?ids=${encodeURIComponent(selectedIds.join(","))}`;
    navigate(`/report/${anchor}${qs}`);
  }


  return (
    <>
      <h2>最新内容</h2>

      {/* 顶部：日期范围 + 快捷选择 */}
      <div className="mt-4 p-4 border rounded-lg">
        <div className="flex flex-wrap items-end gap-3">
          <div className="grow">
            <div className="font-medium">按日期范围选择</div>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-2 text-sm">
                <span>开始</span>
                <input
                  type="date"
                  value={rangeStart}
                  onChange={(e) => setRangeStart(e.target.value)}
                  className="border rounded px-2 py-1"
                />
              </div>
              <div className="flex items-center gap-2 text-sm">
                <span>结束</span>
                <input
                  type="date"
                  value={rangeEnd}
                  onChange={(e) => setRangeEnd(e.target.value)}
                  className="border rounded px-2 py-1"
                />
              </div>
              <Button size="sm" onClick={applyRange}>应用范围到多选</Button>
              <Button size="sm" variant="outline" onClick={() => { setRangeStart(""); setRangeEnd(""); }}>清空</Button>
            </div>
          </div>

          {/* 快捷：当天 / 近7天（仅改变展示选择） */}
          <div className="flex items-center gap-2">
            <Button size="sm" onClick={quickToday}>选择「今天」</Button>
            <Button size="sm" variant="outline" onClick={quickLast7Days}>选择「近7天」</Button>
          </div>
        </div>
      </div>

      {/* 保留原有：逐日多选 */}
      <div className="my-4">
        <p className="mb-2 text-sm text-slate-500">选择一个或多个日期：</p>
        <DateMultiPicker dates={allDates} selected={selectedDates} onChange={setSelectedDates} />
      </div>

      {/* 标签筛选 */}
      <div className="mt-4 p-4 border rounded-lg">
        <div className="flex items-center justify-between">
          <div className="font-medium">按标签筛选</div>
          <div className="text-sm text-gray-500">{tagsQuery.isLoading ? "加载标签…" : `可选 ${allTagItems.length} 个`}</div>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {allTagItems.map((t) => {
            const active = selectedTagIds.includes(t.id);
            return (
              <button
                key={t.id}
                type="button"
                onClick={() =>
                  setSelectedTagIds((prev) => (prev.includes(t.id) ? prev.filter((x) => x !== t.id) : [...prev, t.id]))
                }
                className={[
                  "px-3 py-1 rounded-full border text-sm transition",
                  active ? "bg-blue-600 text-white border-blue-600" : "bg-gray-50 text-gray-700 border-gray-200 hover:bg-gray-100",
                ].join(" ")}
              >
                {t.name}
              </button>
            );
          })}
          {allTagItems.length === 0 && <span className="text-sm text-gray-400">暂无可用标签</span>}
        </div>
        {selectedTagIds.length > 0 && (
          <div className="mt-3 flex items-center gap-3">
            <span className="text-sm text-gray-600">已选：{selectedTagIds.map((id) => tagIdToName.get(id) || id).join("、")}</span>
            <Button size="sm" variant="outline" onClick={() => setSelectedTagIds([])}>清除标签</Button>
          </div>
        )}
      </div>

      {/* 操作区 */}
      <div className="mb-4 mt-4 flex flex-wrap gap-3 items-center">
        {/* 单一生成按钮：根据“勾选的内容 + 上方选择条件”调用固定函数 */}
        <Button onClick={reportSelected}>根据选择生成报告</Button>
        <span className="text-sm text-slate-500">已选 {selectedIds.length} 条</span>

        {/* 全选/反选/清空 —— 作用于“当前过滤后可见列表” */}
        <div className="ml-auto flex gap-2 items-center">
          <Button size="sm" variant="outline" onClick={selectAllVisible}>全选可见</Button>
          <Button size="sm" variant="outline" onClick={invertSelection}>反选可见</Button>
          <Button size="sm" variant="ghost" onClick={clearSelection}>清空选择</Button>
        </div>
      </div>

      {isLoading && <p>加载中…</p>}
      {error && <p className="text-red-500">{error.message}</p>}

      {!!(filteredData && filteredData.length) && (
        <div className="grid w-full gap-1.5">
          <div className="flex gap-2 items-center">
            <div className="flex-1">
              <p>勾选需要生成报告的洞见；按钮在上方。</p>
            </div>
          </div>
          <div className="w-full gap-1.5">
            <List
              insights={filteredData}
              selected={selectedInsight}
              selectedIds={selectedIds}
              onToggleSelect={onToggleSelect}
              onOpen={(id) => useClientStore.getState().selectInsight(id)}
              onDelete={(insight_id, article_id) => mutUnlink.mutate({ insight_id, article_id })}
              onMore={() => selectedInsight && mutMore.mutate({ insight_id: selectedInsight })}
              error={null}
              tagIdToName={tagIdToName}
            />
            <p className="text-sm text-muted-foreground mt-4">共 {filteredData.length} 条结果（已合并 {selectedDates.length} 天）</p>
          </div>
        </div>
      )}

      <Toaster />
    </>
  );
}
