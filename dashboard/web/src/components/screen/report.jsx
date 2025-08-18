// pages/ReportScreen.jsx
import { useEffect, useState } from "react";
import { useLocation, useParams } from "wouter";
import { useMutation, useQueryClient, useQueries } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { ButtonLoading } from "@/components/ui/button-loading";
import { FileDown } from "lucide-react";
import {
  generateReport,
  reviseReport,
  clearReportMemory,
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

  // —— 当前选择签名：用于控制下载区块避免展示旧报告
  const currentSig = selectedIds.length ? selectedIds.slice().sort().join(",") : "";

  // —— 仅当“本次点击生成”后才显示下载（多选时）
  const [justGeneratedSig, setJustGeneratedSig] = useState("");
  useEffect(() => {
    setJustGeneratedSig(""); // 切换选择时重置
  }, [currentSig]);

  // —— 基础路由检查
  useEffect(() => {
    if (!params || !params.insight_id) {
      navigate("/insights", { replace: true });
    }
  }, []);

  // —— 锚点洞见（承载 docx）
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
    mutationFn: async (data) => generateReport(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["insight", params.insight_id] });
      setJustGeneratedSig(currentSig);
    },
  });

  // ===== /report/revise =====
  const reviseMut = useMutation({
    mutationFn: async (data) => reviseReport(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["insight", params.insight_id] });
      setJustGeneratedSig(currentSig);
    },
  });

  // ===== /report/clear_memory =====
  const clearMemMut = useMutation({
    mutationFn: async (data) => clearReportMemory(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["insight", params.insight_id] });
    },
  });

  const isBusy = generateMut.isPending || reviseMut.isPending || clearMemMut.isPending;

  // —— 首次生成（严格不读记忆）
  function submitGenerate() {
    const payload = {
      insight_id: params.insight_id, // 锚点不变
      insight_ids: selectedIds.length ? selectedIds : undefined, // 合并生成
      toc: [""], // 留空走后端默认标题；如果你加了标题输入框，就把标题放到 toc[0]
    };
    generateMut.mutate(payload);
  }

  // —— 应用修改（基于记忆）
  function submitRevise() {
    if (!localComment.trim()) return;
    const payload = {
      insight_id: params.insight_id,
      comment: localComment.trim(),
      // 传生成时的 ids 以便后端重拉附录/链接（可选）
      insight_ids_for_footer: selectedIds.length ? selectedIds : undefined,
    };
    reviseMut.mutate(payload);
  }

  // —— 清除记忆
  function submitClearMemory() {
    clearMemMut.mutate({
      insight_id: params.insight_id,
      // 或 { clear_all: true } 清全部
    });
  }

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

      {/* 修改意见（仅用于“应用修改”） */}
      <div className="grid gap-2 max-w-screen-md">
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
              disabled={!localComment.trim()}
              title={localComment.trim() ? "" : "请输入修改意见"}
            >
              应用修改（基于记忆）
            </Button>

            <Button
              variant="destructive"
              onClick={submitClearMemory}
              title="清除此锚点的记忆；下次首次生成不会受旧版本影响"
            >
              清除记忆
            </Button>
          </>
        )}

        {!isBusy && (
          <Button variant="outline" onClick={() => navigate("/insights")}>
            选择其他分析结果
          </Button>
        )}
      </div>

      {/* 下载区域（多选需“本次生成完成”才显示；单条保持历史可见） */}
      {(() => {
        const canShowDownload =
          !!query.data?.docx && (!idsParam ? true : justGeneratedSig === currentSig);
        return !isBusy && canShowDownload;
      })() && (
        <div className="grid gap-1.5 max-w-screen-md border rounded px-4 py-2 pb-6">
          <p className="my-4">报告已生成，点击下载</p>
          <p className="bg-slate-100 px-4 py-2 hover:underline flex gap-2 items-center overflow-hidden">
            <FileDown className="h-4 w-4 text-slate-400" />
            <a
              className="truncate"
              href={`${import.meta.env.VITE_PB_BASE}/api/files/${query.data.collectionName}/${query.data.id}/${query.data.docx}`}
              target="_blank"
              rel="noreferrer"
            >
              {query.data.docx}
            </a>
          </p>
        </div>
      )}

      {/* 错误显示 */}
      {query.isError && <p className="text-red-500 my-4">{query.error.message}</p>}
      {generateMut.isError && (
        <p className="text-red-500 my-4">{generateMut.error.message}</p>
      )}
      {reviseMut.isError && <p className="text-red-500 my-4">{reviseMut.error.message}</p>}
      {clearMemMut.isError && (
        <p className="text-red-500 my-4">
          {String(clearMemMut.error?.message || clearMemMut.error)}
        </p>
      )}
    </div>
  );
}

export default ReportScreen;
