// pages/ReportScreen.jsx
import { useEffect, useMemo, useState } from "react";
import { useLocation, useParams, useNavigate } from "react-router-dom";
import { useMutation, useQueryClient, useQueries, useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { ButtonLoading } from "@/components/ui/button-loading";
import { Textarea } from "@/components/ui/textarea";
import { X } from "lucide-react";

import {
  // 后端交互
  generateReport,
  reviseReport,
  // PB 直读
  getReportMemoriesPB,
  // PB 工具
  buildPBFileUrl,
  formatUtcPlus8,
  // 其他已有 hooks/api
  useInsight,
  getInsight,
  useClientStore,
} from "@/store";

/** 读取/写回 URL 中的 ?ids=（保持可分享/刷新） */
function useIdsInUrl() {
  const navigate = useNavigate();
  const location = useLocation();
  const search = typeof window !== "undefined" ? window.location.search : "";
  const idsParam = new URLSearchParams(search).get("ids");
  const initialIds = idsParam
    ? Array.from(new Set(idsParam.split(",").map((s) => s.trim()).filter(Boolean)))
    : [];

  const setIds = (ids) => {
    const qs = new URLSearchParams(location.search);
    if (ids && ids.length) qs.set("ids", ids.join(","));
    else qs.delete("ids");
    navigate(`${location.pathname}?${qs.toString()}`, { replace: true });
  };

  return { initialIds, setIds };
}

export default function ReportScreen() {
  const navigate = useNavigate();
  const params = useParams();
  const queryClient = useQueryClient();

  // 从分析页带来的选择
  const { initialIds, setIds } = useIdsInUrl();
  const [selectedIds, setSelectedIds] = useState(initialIds);

  // 当前锚点（用于承载与上传 docx）
  const anchorId = params?.insight_id || null;
  const anchorQuery = anchorId ? useInsight(anchorId) : { data: null, isError: false, error: null };

  // 展示用：并发拉取已选洞见详情
  const selectedQueries = useQueries({
    queries: (selectedIds || []).map((id) => ({
      queryKey: ["insight", id],
      queryFn: () => getInsight(id),
      enabled: !!id,
    })),
  });
  const selectedLoading = selectedQueries.some((q) => q.isLoading);
  const selectedError = selectedQueries.find((q) => q.isError)?.error;
  const selectedDetails = selectedQueries.map((q) => q.data).filter(Boolean);

  // 历史报告列表（PB）
  const memoriesQuery = useQuery({
    queryKey: ["report_memories_pb_all"],
    queryFn: getReportMemoriesPB,
  });
  const memories = useMemo(() => {
    const arr = Array.isArray(memoriesQuery.data) ? memoriesQuery.data : [];
    return arr.map((r) => ({
      id: r.id,
      title: r.title || "(未命名)",
      docx: r.docx || "",
      docx_url: buildPBFileUrl(r) || "",
      updated: r.updated || r.created || "",
      created: r.created || "",
    }));
  }, [memoriesQuery.data]);

  // 选择的历史报告（作为“应用修改”的基底）
  const [selectedMemoryId, setSelectedMemoryId] = useState("");
  const [lastMemoryId, setLastMemoryId] = useState("");
  useEffect(() => {
    if (lastMemoryId) {
      setSelectedMemoryId(lastMemoryId);
      return;
    }
    if (!selectedMemoryId && memories.length) setSelectedMemoryId(memories[0].id);
  }, [memories, lastMemoryId, selectedMemoryId]);

  // 修改意见（来自全局 store）
  const commentFromStore = useClientStore((s) => s.comment);
  const updateComment = useClientStore((s) => s.updateComment);
  const [localComment, setLocalComment] = useState(commentFromStore || "");
  useEffect(() => setLocalComment(commentFromStore || ""), [commentFromStore]);
  const onChangeComment = (e) => {
    setLocalComment(e.target.value);
    updateComment(e.target.value);
  };

  // 生成 / 修订
  const generateMut = useMutation({
    mutationFn: (data) => generateReport(data),
    onSuccess: (res) => {
      if (anchorId) queryClient.invalidateQueries({ queryKey: ["insight", anchorId] });
      queryClient.invalidateQueries({ queryKey: ["report_memories_pb_all"] });
      setLastMemoryId(res?.data?.memory_id || "");
    },
  });
  const reviseMut = useMutation({
    mutationFn: (data) => reviseReport(data),
    onSuccess: (res) => {
      if (anchorId) queryClient.invalidateQueries({ queryKey: ["insight", anchorId] });
      queryClient.invalidateQueries({ queryKey: ["report_memories_pb_all"] });
      setLastMemoryId(res?.data?.memory_id || "");
    },
  });
  const isBusy = generateMut.isPending || reviseMut.isPending;

  // 操作：首次生成（不读记忆）
  function submitGenerate() {
    if (!anchorId) return;
    generateMut.mutate({
      insight_id: anchorId,
      insight_ids: selectedIds.length ? selectedIds : undefined, // 合并
      toc: [""],
    });
  }
  // 操作：应用修改（基于所选历史报告）
  function submitRevise() {
    if (!anchorId || !localComment.trim() || !selectedMemoryId) return;
    reviseMut.mutate({
      insight_id: anchorId,
      memory_id: selectedMemoryId,
      comment: localComment.trim(),
      insight_ids_for_footer: selectedIds.length ? selectedIds : undefined,
    });
  }

  // 从当前选择里删除某个洞见（卡片删除按钮）
  function removeSelected(id) {
    const next = (selectedIds || []).filter((x) => x !== id);
    setSelectedIds(next);
    setIds(next); // 同步到 URL
  }

  // 空状态：不跳转，给按钮
  const isEmpty = selectedIds.length === 0;

  return (
    <div className="text-left">
      <h2 className="max-w-screen-md mb-3">报告生成 / 修改</h2>

      {/* —— 已选洞见（卡片） —— */}
      <div className="max-w-screen-md mb-4">
        <div className="flex items-center justify-between mb-2">
          <div className="font-medium">已选洞见</div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => navigate("/insights")}>
              去洞见页挑选
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => {
                setSelectedIds([]);
                setIds([]);
              }}
              disabled={isEmpty}
            >
              清空
            </Button>
          </div>
        </div>

        {isEmpty ? (
          <div className="text-slate-500 text-sm border rounded p-3">
            还没有选择任何洞见。请点击右上角按钮<b>「去洞见页挑选」</b> 添加。
          </div>
        ) : (
          <>
            {selectedLoading && <div className="text-slate-500 text-sm mb-2">加载选中洞见内容中…</div>}
            {selectedError && (
              <div className="text-red-500 text-sm mb-2">加载失败：{String(selectedError?.message || selectedError)}</div>
            )}

            <div className="grid gap-3">
              {(selectedDetails || []).map((ins) => (
                <div
                  key={ins.id}
                  className="relative border rounded p-3 bg-white shadow-sm hover:shadow transition text-slate-800"
                >
                  <button
                    className="absolute top-2 right-2 p-1 rounded hover:bg-red-50"
                    title="移除该洞见"
                    onClick={() => removeSelected(ins.id)}
                  >
                    <X className="h-4 w-4 text-slate-500 hover:text-red-600" />
                  </button>
                  <div className="text-xs text-slate-400 mb-1">{ins.id}</div>
                  <div className="whitespace-pre-wrap break-words">{ins.content}</div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      {/* —— 单选模式的锚点提示（可选展示） —— */}
      {!isEmpty && !anchorQuery.data && (
        <div className="text-slate-500 text-sm mb-4">
          当前路由未提供 <code>:insight_id</code> 作为上传锚点；首次生成/修改需要在路由中指定锚点，或在洞见页通过“生成报告”进入。
        </div>
      )}

      {/* —— 历史报告 —— */}
      <div className="grid gap-2 max-w-screen-md">
        <h3 className="my-2">历史报告（选择一条作为“应用修改”的基底）</h3>
        {memoriesQuery.isLoading && <div className="text-slate-500">加载历史报告中…</div>}
        {memoriesQuery.isError && (
          <div className="text-red-500">加载失败：{String(memoriesQuery.error?.message || memoriesQuery.error)}</div>
        )}
        {!memoriesQuery.isLoading && memories.length === 0 && <div className="text-slate-500">暂无历史报告</div>}
        {!memoriesQuery.isLoading && memories.length > 0 && (
          <ul className="border rounded divide-y">
            {memories.map((m) => (
              <li key={m.id} className="flex items-center gap-3 p-3">
                <input
                  type="radio"
                  name="memory"
                  className="h-4 w-4"
                  checked={selectedMemoryId === m.id}
                  onChange={() => setSelectedMemoryId(m.id)}
                />
                <div className="flex-1 min-w-0">
                  <div className="font-medium truncate">{m.title}</div>
                  <div className="text-xs text-slate-500 mt-0.5">更新时间：{formatUtcPlus8(m.updated)}</div>
                  {m.docx_url && (
                    <a
                      className="text-sm text-blue-600 hover:underline break-all"
                      href={m.docx_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {m.docx || "下载 DOCX"}
                    </a>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* —— 修改意见 —— */}
      <div className="grid gap-2 max-w-screen-md mt-6">
        <h3 className="my-2">修改意见</h3>
        <Textarea
          placeholder="示例：1）标题突出××；2）综述补充国家发改委口径；3）行业动态-核能条目更简洁；4）时间统一为YYYY年M月D日。"
          rows={6}
          value={localComment}
          onChange={onChangeComment}
        />
        <small className="text-slate-500">
          结构（分区/编号）将被严格保留；首次生成不会读取这里，仅“应用修改”时使用。
        </small>
      </div>

      {/* —— 操作按钮 —— */}
      <div className="my-6 flex flex-col gap-3 w-max">
        {isBusy ? (
          <ButtonLoading />
        ) : (
          <>
            <Button onClick={submitGenerate} disabled={!anchorId}>
              首次生成
            </Button>
            <Button
              variant="outline"
              onClick={submitRevise}
              disabled={!anchorId || !localComment.trim() || !selectedMemoryId}
              title={
                !anchorId
                  ? "缺少路由参数 :insight_id（建议从洞见页点击生成报告进入）"
                  : !localComment.trim()
                  ? "请输入修改意见"
                  : !selectedMemoryId
                  ? "请选择一条历史报告"
                  : ""
              }
            >
              应用修改（基于所选历史报告）
            </Button>
          </>
        )}

        {!isBusy && (
          <Button variant="outline" onClick={() => navigate("/insights")}>
            返回洞见页
          </Button>
        )}
      </div>

      {/* —— 错误提示 —— */}
      {anchorQuery.isError && <p className="text-red-500 my-4">{anchorQuery.error.message}</p>}
      {generateMut.isError && <p className="text-red-500 my-4">{String(generateMut.error?.message || generateMut.error)}</p>}
      {reviseMut.isError && <p className="text-red-500 my-4">{String(reviseMut.error?.message || reviseMut.error)}</p>}
    </div>
  );
}
