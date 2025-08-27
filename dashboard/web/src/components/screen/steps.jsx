import StepLayout from "@/components/layout/step";
import { useLocation, useNavigate } from "react-router-dom";

const TITLE = "鹰眼AI头条";

const order = ["/start", "/articles", "/insights", "/report"];

export default function Steps() {
  const { pathname } = useLocation();
  const navigate = useNavigate();

  const idx = Math.max(0, order.indexOf(pathname));
  const titles = ["信源管理", "最新内容", "行业洞察", "生成报告"];
  const title = `${TITLE} > ${titles[idx] || "步骤"}`;

  const go = (to) => navigate(to);
  const next = () => idx < order.length - 1 && navigate(order[idx + 1]);
  const prev = () => idx > 0 && navigate(order[idx - 1]);

  return (
    <StepLayout title={title} isPending={false} navigate={go} prev={prev} next={next}>
      {/* 这里只是外壳，内容由路由决定（见 App.jsx 的 Routes） */}
    </StepLayout>
  );
}
