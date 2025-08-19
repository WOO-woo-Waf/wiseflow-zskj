// pages/ReportScreen.jsx
import { useEffect, useMemo, useState } from "react";
import { useLocation, useParams } from "wouter";
import { useMutation, useQueryClient, useQueries, useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { ButtonLoading } from "@/components/ui/button-loading";
import { FileDown } from "lucide-react";
import {
  // 后端交互
  generateReport,
  reviseReport,
  // PB 直读（不再按 anchor 过滤，直接全量/或你在 store 内部自行加过滤）
  getReportMemoriesPB,
  // PB 工具
  buildPBFileUrl,        // 统一用它拼出 {VITE_PB_BASE}/api/files/{collection}/{id}/{filename}
  formatUtcPlus8,        // 固定把 PB 的 UTC -> UTC+8
  // 其他已有 hooks/api
  useInsight,
  getInsight,
  useClientStore,
} from "@/store";
import { Textarea } from "@/components/ui/textarea";

function ReportScreen() {
  const [, navigate] = useLocation();
  const params = useParams();

  // —— 多选：从 ?ids=... 读取
  const search = typeof window !== "undefined" ? window.location.search : "";
  const idsParam = new URLSearchParams(search).get("ids");
  const selectedIds = idsParam
    ? Array.from(new Set(idsParam.split(",").map((s) => s.trim()).filter(Boolean)))
    : [];

  // —— 当前选择签名：用于控制“本次运行后才显示下载（多选）”
  const currentSig = selectedIds.length ? selectedIds.slice().sort().join(",") : "";
  const [justRanSig, setJustRanSig] = useState("");
  useEffect(() => setJustRanSig(""), [currentSig]);

  // —— 基础路由检查
  useEffect(() => {
    if (!params || !params.insight_id) navigate("/insights", { replace: true });
  }, []);

  // —— 锚点洞见（承载旧 docx 字段；生成或修改后仍刷新它）
  const query = useInsight(params.insight_id);
  const queryClient = useQueryClient();

  // —— 拉取多选洞见详情，展示“已选择分析结果”
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

  // —— PB 直读：report_memories（全量或 store 内部已按你需要过滤）
  const memoriesQuery = useQuery({
    queryKey: ["report_memories_pb_all"],
    queryFn: getReportMemoriesPB,
  });

  // 统一字段 & 预先生成下载 URL（用 buildPBFileUrl）
  const memories = useMemo(() => {
    const arr = Array.isArray(memoriesQuery.data) ? memoriesQuery.data : [];
    return arr.map((r) => {
      const url = buildPBFileUrl(r); // {VITE_PB_BASE}/api/files/{collectionName}/{id}/{docx}
      return {
        id: r.id,
        title: r.title || "(未命名)",
        docx: r.docx || "",
        docx_url: url || "",
        collectionName: r.collectionName || "report_memories",
        updated: r.updated || r.created || "",
        created: r.created || "",
      };
    });
  }, [memoriesQuery.data]);

  // —— 选择的记忆ID（“应用修改”的基底）
  const [selectedMemoryId, setSelectedMemoryId] = useState("");
  // —— 记录本次生成/修改后后端回传的新 memory_id（若后端返回）
  const [lastMemoryId, setLastMemoryId] = useState("");

  useEffect(() => {
    // 列表变化后默认选最新；如果后端刚回了 memory_id，就优先选它
    if (lastMemoryId) {
      setSelectedMemoryId(lastMemoryId);
      return;
    }
    if (!selectedMemoryId && memories.length) {
      setSelectedMemoryId(memories[0].id);
    }
  }, [memories, lastMemoryId, selectedMemoryId]);

  // —— 修改意见（用于“应用修改”）
  const commentFromStore = useClientStore((s) => s.comment);
  const updateComment = useClientStore((s) => s.updateComment);
  const [localComment, setLocalComment] = useState(commentFromStore || "");
  useEffect(() => setLocalComment(commentFromStore || ""), [commentFromStore]);
  const onChangeComment = (e) => {
    setLocalComment(e.target.value);
    updateComment(e.target.value);
  };

  // ===== /report/generate =====
  const generateMut = useMutation({
    mutationFn: (data) => generateReport(data),
    onSuccess: (res) => {
      // 刷新锚点 & 记忆列表（PB 直读）
      queryClient.invalidateQueries({ queryKey: ["insight", params.insight_id] });
      queryClient.invalidateQueries({ queryKey: ["report_memories_pb_all"] });
      setJustRanSig(currentSig);
      // 兼容：后端若返回 memory_id，则默认选它
      setLastMemoryId(res?.data?.memory_id || "");
    },
  });

  // ===== /report/revise =====
  const reviseMut = useMutation({
    mutationFn: (data) => reviseReport(data),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ["insight", params.insight_id] });
      queryClient.invalidateQueries({ queryKey: ["report_memories_pb_all"] });
      setJustRanSig(currentSig);
      setLastMemoryId(res?.data?.memory_id || "");
    },
  });

  const isBusy = generateMut.isPending || reviseMut.isPending;

  // —— 首次生成（严格不读记忆）
  function submitGenerate() {
    generateMut.mutate({
      insight_id: params.insight_id,                        // 锚点用于上传 docx
      insight_ids: selectedIds.length ? selectedIds : undefined, // 合并生成
      toc: [""],                                            // 留空走后端默认标题
    });
  }

  // —— 应用修改（基于所选记忆）
  function submitRevise() {
    if (!localComment.trim() || !selectedMemoryId) return;
    reviseMut.mutate({
      insight_id: params.insight_id,          // 用于上传 docx 的目标 insight
      memory_id: selectedMemoryId,            // 指定基底记忆
      comment: localComment.trim(),
      insight_ids_for_footer: selectedIds.length ? selectedIds : undefined,
    });
  }

  // —— 下载链接：用“所选历史报告”的 docx_url（用 buildPBFileUrl 生成）
  const currentDownload = useMemo(() => {
    const m = memories.find((x) => x.id === selectedMemoryId);
    return m?.docx_url ? { url: m.docx_url, filename: m.docx || m.title } : null;
  }, [memories, selectedMemoryId]);

  return (
    <div className="text-left">
      <div>
        <h2 className="max-w-screen-md">报告生成 / 修改</h2>

        <h3 className="my-4">已选择分析结果：</h3>
        {selectedIds.length > 1 ? (
          <div className="bg-slate-100 px-4 py-3 mb-4 text-slate-700 max-w-screen-md space-y-4">
            <div className="font-medium">共选择 {selectedIds.length} 条洞见</div>
            {selectedLoading && <div className="text-slate-500">加载选中洞见内容中…</div>}
            {selectedError && (
              <div className="text-red-500">
                加载失败：{String(selectedError?.message || selectedError)}
              </div>
            )}
            {!selectedLoading && selectedDetails.length > 0 && (
              <ol className="list-decimal pl-5 space-y-3">
                {selectedDetails.map((ins) => (
                  <li key={ins.id} className="whitespace-pre-wrap break-words">
                    {ins.content}
                  </li>
                ))}
              </ol>
            )}
          </div>
        ) : (
          query.data && (
            <div className="bg-slate-100 px-4 py-3 mb-4 text-slate-700 max-w-screen-md whitespace-pre-wrap break-words">
              {query.data.content}
            </div>
          )
        )}
      </div>

      {/* 历史报告（来自 PB.report_memories 全量） */}
      <div className="grid gap-2 max-w-screen-md">
        <h3 className="my-2">历史报告（选择一条作为“应用修改”的基底）</h3>
        {memoriesQuery.isLoading && <div className="text-slate-500">加载历史报告中…</div>}
        {memoriesQuery.isError && (
          <div className="text-red-500">
            加载失败：{String(memoriesQuery.error?.message || memoriesQuery.error)}
          </div>
        )}
        {!memoriesQuery.isLoading && memories.length === 0 && (
          <div className="text-slate-500">暂无历史报告</div>
        )}
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
                  <div className="text-xs text-slate-500 mt-0.5">
                    更新时间：{formatUtcPlus8(m.updated)}
                  </div>
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

      {/* 修改意见 */}
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

      {/* 操作按钮 */}
      <div className="my-6 flex flex-col gap-3 w-max">
        {isBusy ? (
          <ButtonLoading />
        ) : (
          <>
            <Button onClick={submitGenerate}>首次生成</Button>
            <Button
              variant="outline"
              onClick={submitRevise}
              disabled={!localComment.trim() || !selectedMemoryId}
              title={
                !localComment.trim()
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
            选择其他分析结果
          </Button>
        )}
      </div>


      {/* 错误显示 */}
      {query.isError && <p className="text-red-500 my-4">{query.error.message}</p>}
      {generateMut.isError && (
        <p className="text-red-500 my-4">
          {String(generateMut.error?.message || generateMut.error)}
        </p>
      )}
      {reviseMut.isError && (
        <p className="text-red-500 my-4">
          {String(reviseMut.error?.message || reviseMut.error)}
        </p>
      )}
    </div>
  );
}

export default ReportScreen;
