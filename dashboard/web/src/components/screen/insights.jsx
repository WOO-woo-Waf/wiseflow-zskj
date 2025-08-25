// InsightsScreen.jsx  —— 支持“多天选择 + 跨天合并生成报告 + 标签筛选”
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import { Files } from "lucide-react";

import { ArticleList } from "@/components/article-list";
import { Button } from "@/components/ui/button";
import { ButtonLoading } from "@/components/ui/button-loading";
import { Toaster } from "@/components/ui/toaster";
import { useToast } from "@/components/ui/use-toast";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";

// 这些按你的项目实际路径调整
import {
  getInsights,
  getInsightDates,
  useClientStore,
  unlinkArticle,
  more,
  // 👇 新增：引入 useTags
  useTags,
} from "@/store";

/** ---------- 工具 ---------- */
// 统一把 tag 字段变成 id 数组（兼容 string / array / null）
function normalizeTagIds(tagField) {
  if (tagField == null) return [];
  if (Array.isArray(tagField)) return tagField.filter(Boolean).map(String);
  return [String(tagField)];
}

/** ---------- 多选日期控件 ---------- */
function DateMultiPicker({ dates, selected, onChange }) {
  function toggle(d, checked) {
    onChange(checked ? Array.from(new Set([...selected, d])) : selected.filter((x) => x !== d));
  }
  return (
    <div className="flex flex-wrap gap-2">
      {dates.map((d) => (
        <label key={d} className="flex items-center gap-1 text-sm border rounded px-2 py-1 cursor-pointer">
          <input
            type="checkbox"
            checked={selected.includes(d)}
            onChange={(e) => toggle(d, e.target.checked)}
          />
          {d}
        </label>
      ))}
    </div>
  );
}

/** ---------- 多天洞见并发拉取并合并 ---------- */
function useInsightsMulti(selectedDates) {
  const queries = useQueries({
    queries: (selectedDates || []).map((d) => ({
      queryKey: ["insights", d],
      queryFn: () => getInsights(d),
      enabled: !!d,
      staleTime: 60_000,
    })),
  });

  const isLoading = queries.some((q) => q.isLoading);
  const isError = queries.some((q) => q.isError);
  const errorObj = queries.find((q) => q.error)?.error;

  // 合并各天结果，按 created 倒序（与 getInsights 保持一致）
  const data = useMemo(() => {
    const list = queries.map((q) => (Array.isArray(q.data) ? q.data : [])).flat();
    return list.sort((a, b) => (a.created > b.created ? -1 : 1));
  }, [JSON.stringify(queries.map((q) => q.data))]);

  return { data, isLoading, isError, error: errorObj };
}

/** ---------- 列表 ---------- */
function List({
  insights,
  selected,
  selectedIds,
  onToggleSelect,
  onOpen,
  onDelete,
  onReport,
  onMore,
  isGettingMore,
  error,
  // 👇 新增：用于把 id 映射为标签名
  tagIdToName,
}) {
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
                  {/* 👇 新增：在标题下方小字展示标签名 */}
                  {tagNames.length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {tagNames.map((name) => (
                        <span
                          key={name}
                          className="text-[11px] px-2 py-[2px] rounded-full bg-gray-100 text-gray-600 border"
                        >
                          {name}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <div className="flex items-center justify-center gap-1">
                  <Files className="h-4 w-4 text-slate-400" />
                  <span className="text-slate-400 text-sm leading-none">
                    x {insight.expand?.articles?.length ?? 0}
                  </span>
                </div>
              </div>
            </AccordionTrigger>
            <AccordionContent className="px-4">
              <ArticleList data={insight.expand?.articles ?? []} showActions={true} onDelete={unlink} />
              {error && <p className="text-red-500 my-4">{error.message}</p>}
              <div className="mt-2 flex gap-2">
                <Button variant="outline" size="sm" onClick={onReport}>生成单条报告</Button>
              </div>
            </AccordionContent>
          </AccordionItem>
        );
      })}
    </Accordion>
  );
}

/** ---------- 主页面 ---------- */
export default function InsightsScreen() {
  const [selectedIds, setSelectedIds] = useState([]);
  const [selectedDates, setSelectedDates] = useState([]); // ✅ 多天选择
  const selectedInsight = useClientStore((s) => s.selectedInsight);
  const selectInsight = useClientStore((s) => s.selectInsight);

  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  // 可选日期
  const [allDates, setAllDates] = useState([]);
  useEffect(() => {
    getInsightDates().then((ds) => {
      setAllDates(ds || []);
      if ((ds || []).length && selectedDates.length === 0) setSelectedDates([ds[0]]); // 默认选最近一天
    });
  }, []);

  // 并发拉取 & 合并
  const { data, isLoading, error } = useInsightsMulti(selectedDates);

  // ===== 新增：读取 tags 集合 & 映射 id->name =====
  const tagsQuery = useTags();
  const tagIdToName = useMemo(() => {
    const map = new Map();
    (tagsQuery.data || []).forEach((t) => map.set(String(t.id), String(t.name ?? t.id)));
    return map;
  }, [tagsQuery.data]);

  // ===== 新增：标签筛选（chips）
  const [selectedTagIds, setSelectedTagIds] = useState([]);
  const allTagItems = useMemo(() => {
    const items = (tagsQuery.data || []).map((t) => ({ id: String(t.id), name: String(t.name ?? t.id) }));
    return items.sort((a, b) => a.name.localeCompare(b.name, "zh-Hans-CN"));
  }, [tagsQuery.data]);

  // 删除文章
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
    onSuccess: () => {
      selectedDates.forEach((d) => queryClient.invalidateQueries({ queryKey: ["insights", d] }));
    },
    onError: (e) => {
      toast({ variant: "destructive", title: "出错啦！", description: e?.message || "操作失败" });
    },
  });

  // “更多”
  const mutMore = useMutation({
    mutationFn: (params) => more(params),
    onSuccess: () => {
      selectedDates.forEach((d) => queryClient.invalidateQueries({ queryKey: ["insights", d] }));
    },
    onError: (e) => {
      toast({ variant: "destructive", title: "出错啦！", description: e?.message || "加载失败" });
    },
  });

  // 切换日期时清空选择
  useEffect(() => {
    selectInsight(null);
    setSelectedIds([]);
  }, [JSON.stringify(selectedDates)]);

  // 勾选切换
  function onToggleSelect(id, checked) {
    setSelectedIds((prev) => (checked ? (prev.includes(id) ? prev : [...prev, id]) : prev.filter((x) => x !== id)));
  }

  function unlink(insight_id, article_id) {
    mutUnlink.mutate({ insight_id, article_id });
  }

  function reportSingle() {
    if (!selectedInsight) return;
    navigate(`/report/${selectedInsight}`);
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

  // 生成“所选日期全部洞见”（跨天）
  function reportAllSelectedDays() {
    const ids = (filteredData || []).map((i) => i.id); // 注意：按筛选后的集合生成
    if (!ids.length) {
      toast({ title: "暂无数据", description: "所选条件没有洞见", variant: "destructive" });
      return;
    }
    const anchor = ids[0];
    const qs = `?ids=${encodeURIComponent(ids.join(","))}`;
    navigate(`/report/${anchor}${qs}`);
  }

  // ===== 新增：按标签过滤（与多天合并后的 data 叠加）
  const filteredData = useMemo(() => {
    if (!selectedTagIds.length) return data || [];
    return (data || []).filter((ins) => {
      const ids = normalizeTagIds(ins.tag);
      return ids.some((id) => selectedTagIds.includes(String(id)));
    });
  }, [data, selectedTagIds]);

  return (
    <>
      <h2>分析结果</h2>

      {/* 多选日期 */}
      <div className="my-4">
        <p className="mb-2 text-sm text-slate-500">选择一个或多个日期：</p>
        <DateMultiPicker dates={allDates} selected={selectedDates} onChange={setSelectedDates} />
      </div>

      {/* ===== 新增：标签筛选（位于日期选择下面，独立卡片） ===== */}
      <div className="mt-4 p-4 border rounded-lg">
        <div className="flex items-center justify-between">
          <div className="font-medium">按标签筛选</div>
          <div className="text-sm text-gray-500">
            {tagsQuery.isLoading ? "加载标签…" : `可选 ${allTagItems.length} 个`}
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {allTagItems.map((t) => {
            const active = selectedTagIds.includes(t.id);
            return (
              <button
                key={t.id}
                type="button"
                onClick={() =>
                  setSelectedTagIds((prev) =>
                    prev.includes(t.id) ? prev.filter((x) => x !== t.id) : [...prev, t.id]
                  )
                }
                className={[
                  "px-3 py-1 rounded-full border text-sm transition",
                  active
                    ? "bg-blue-600 text-white border-blue-600"
                    : "bg-gray-50 text-gray-700 border-gray-200 hover:bg-gray-100",
                ].join(" ")}
              >
                {t.name}
              </button>
            );
          })}
          {allTagItems.length === 0 && (
            <span className="text-sm text-gray-400">暂无可用标签</span>
          )}
        </div>

        {selectedTagIds.length > 0 && (
          <div className="mt-3 flex items-center gap-3">
            <span className="text-sm text-gray-600">
              已选：{selectedTagIds.map((id) => tagIdToName.get(id) || id).join("、")}
            </span>
            <Button size="sm" variant="outline" onClick={() => setSelectedTagIds([])}>清除标签</Button>
          </div>
        )}
      </div>

      {/* 操作区 */}
      <div className="mb-4 mt-4 flex gap-3 items-center">
        <Button onClick={reportAllSelectedDays}>生成所选日期报告</Button>
        <Button variant="outline" onClick={reportSelected}>生成勾选报告</Button>
        <span className="text-sm text-slate-500">已选 {selectedIds.length} 条</span>
      </div>

      {isLoading && <p>加载中…</p>}
      {error && <p className="text-red-500">{error.message}</p>}

      {!!(filteredData && filteredData.length) && (
        <div className="grid w-full gap-1.5">
          <div className="flex gap-2 items-center">
            <div className="flex-1">
              <p>选择一项结果生成文档，或勾选多项后点击上方按钮生成合并报告</p>
            </div>
          </div>
          <div className="w-full gap-1.5">
            <List
              insights={filteredData}
              selected={selectedInsight}
              selectedIds={selectedIds}
              onToggleSelect={onToggleSelect}
              onOpen={(id) => useClientStore.getState().selectInsight(id)}
              onDelete={(insight_id, article_id) => unlink(insight_id, article_id)}
              onReport={reportSingle}
              onMore={() => selectedInsight && mutMore.mutate({ insight_id: selectedInsight })}
              isGettingMore={mutMore.isPending}
              error={null}
              // 👇 传给子组件做名称展示
              tagIdToName={tagIdToName}
            />
            <p className="text-sm text-muted-foreground mt-4">
              共 {filteredData.length} 条结果（已合并 {selectedDates.length} 天）
            </p>
          </div>
        </div>
      )}

      <div className="my-6 flex flex-col gap-4 w-36 text-left">
        <Button variant="outline" onClick={() => navigate("/articles")}>查看所有文章</Button>
        <a href={`${import.meta.env.VITE_PB_BASE}/_/`} target="__blank" className="text-sm underline">
          数据库管理 &gt;
        </a>
      </div>

      <Toaster />
    </>
  );
}
