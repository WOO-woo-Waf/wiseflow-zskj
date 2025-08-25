import { useEffect, useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";

/** 两行合并为一段，逐字打出（更慢） */
function TypingBlock({ lines, speed = 75 }) {
  const full = lines.join("\n");
  const [idx, setIdx] = useState(0);

  useEffect(() => {
    if (idx < full.length) {
      const t = setTimeout(() => setIdx(i => i + 1), speed);
      return () => clearTimeout(t);
    }
  }, [idx, full, speed]);

  const shown = full.slice(0, idx);
  return (
    <div className="whitespace-pre-line">
      {shown}
      <span className="ml-0.5 inline-block w-[1ch] animate-pulse">|</span>
    </div>
  );
}

export default function LandingScreen() {
  const navigate = useNavigate();

  const features = useMemo(
    () => [
      { title: "智能化", desc: "自动采集、理解与推理，实时输出可执行洞察。" },
      { title: "定制化", desc: "按行业/业务场景深度定制指标与知识图谱。" },
      { title: "生成式（人工智能）", desc: "报告、摘要与问答一键生成，提升决策效率。" },
      { title: "一站式", desc: "内嵌璇玑·玉衡、千问等先进大模型，一体化体验。" },
    ],
    []
  );

  return (
    <div className="relative min-h-screen">
      {/* 背景：渐变 + 网格 + 光斑 */}
      <div className="absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-sky-50 via-white to-indigo-50" />
        <svg className="absolute inset-0 w-full h-full opacity-[0.18]">
          <defs>
            <pattern id="grid" width="28" height="28" patternUnits="userSpaceOnUse">
              <path d="M28 0H0V28" fill="none" stroke="#c7d2fe" strokeWidth="0.6" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#grid)" />
        </svg>
        <div className="absolute -top-24 -left-24 w-96 h-96 rounded-full bg-sky-300/25 blur-3xl" />
        <div className="absolute -bottom-28 -right-28 w-[30rem] h-[30rem] rounded-full bg-indigo-300/25 blur-3xl" />
      </div>

      {/* 主体：两栏，更宽松，垂直居中 */}
      <div className="mx-auto max-w-6xl px-6 lg:px-8 py-10 lg:py-16 min-h-screen grid place-items-center">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-10 lg:gap-12 items-center w-full">
          {/* 左列：标题 + 亮点 */}
          <div className="lg:col-span-7">
            <div className="inline-flex items-center rounded-full border px-3 py-1 text-[11px] font-medium text-slate-600 bg-white/80 shadow-sm backdrop-blur">
              卓世科技 · 鹰眼AI头条
            </div>

            {/* 两行逐字，字号更大但行距紧凑 */}
            <h1 className="mt-4 font-extrabold tracking-tight text-slate-900 leading-[1.15]">
              <div className="text-2xl sm:text-3xl lg:text-3xl">
                <TypingBlock
                  speed={75} // 比之前慢
                  lines={[
                    "鹰眼打造行业专属超级情报引擎，",
                    "AI让您的企业拥有超凡洞察力！",
                  ]}
                />
              </div>
            </h1>

            {/* 四个亮点（更宽松的留白） */}
            <div className="mt-10 grid grid-cols-1 sm:grid-cols-2 gap-5 max-w-2xl">
              {features.map((f) => (
                <div
                  key={f.title}
                  className="rounded-2xl border bg-white/80 backdrop-blur p-4 shadow-sm hover:shadow transition"
                >
                  <div className="flex items-start gap-3">
                    <div className="h-7 w-7 shrink-0 rounded-full bg-sky-100 flex items-center justify-center text-[12px] text-sky-600">★</div>
                    <div>
                      <div className="font-semibold text-[16px] text-slate-900">{f.title}</div>
                      <div className="mt-1 text-[13px] text-slate-600 leading-relaxed">{f.desc}</div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* 右列：玻璃拟态登录卡片 */}
          <div className="lg:col-span-5">
            <div
              className="
                mx-auto w-full max-w-md rounded-3xl
                border border-white/40 bg-white/10 backdrop-blur-xl
                shadow-xl p-6 lg:p-7
              "
              style={{
                backgroundImage:
                  "linear-gradient(135deg, rgba(255,255,255,0.16), rgba(255,255,255,0.06))",
              }}
            >
              <div className="flex items-center gap-3">
                {/* 真实 LOGO 可替换为 <img src={logo} ... /> */}
                <div className="h-12 w-12 rounded-xl bg-slate-900/90 text-white flex items-center justify-center font-bold">
                  卓
                </div>
                <div>
                  <div className="text-base font-semibold text-slate-900">卓世科技</div>
                  <div className="text-[11px] text-slate-600">EagleEye Intelligence Engine</div>
                </div>
              </div>

              <p className="mt-4 text-[13px] text-slate-700">
                登录后体验行业专属超级情报引擎：连接数据、分析趋势、生成洞察与报告。
              </p>

              <button
                onClick={() => navigate("/login")}
                className="mt-5 w-full rounded-2xl bg-slate-900 text-white py-2.5 text-[15px] font-medium hover:bg-slate-800 transition focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-slate-900"
              >
                立即体验
              </button>

              <div className="mt-2 text-center text-[11px] text-slate-500">
                已有账号？点击上方按钮进入登录
              </div>
            </div>

            <div className="mt-4 text-center text-[11px] text-slate-400">
              © {new Date().getFullYear()} 卓世科技 · All rights reserved.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
