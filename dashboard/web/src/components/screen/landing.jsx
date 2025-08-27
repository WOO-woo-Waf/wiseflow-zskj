import { useEffect, useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import zh from "@/assets/logo_zh.png";
import zskj from "@/assets/logo_zskj.png";
import yinyan from "@/assets/logo_yinyan.png";

// lucide-react 图标
import { Cpu, Settings, Sparkles, Package } from "lucide-react";

/** 两行合并为一段，逐字打出（更慢） */
function TypingBlock({ lines, speed = 75 }) {
  const full = useMemo(() => (lines || []).join("\n"), [lines]);
  const [idx, setIdx] = useState(0);

  // 文案变化时重置
  useEffect(() => {
    setIdx(0);
  }, [full]);

  useEffect(() => {
    if (idx < full.length) {
      const t = setTimeout(() => setIdx((i) => i + 1), speed);
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

  // 用 icon 字段挂载 lucide 图标组件
  const features = useMemo(
    () => [
      {
        title: "智能化",
        desc: "自动采集、理解与推理，实时输出可执行洞察。",
        icon: Cpu,
      },
      {
        title: "定制化",
        desc: "按行业/业务场景深度定制指标与知识图谱。",
        icon: Settings,
      },
      {
        title: "生成式（人工智能）",
        desc: "报告、摘要与问答一键生成，提升决策效率。",
        icon: Sparkles,
      },
      {
        title: "一站式",
        desc: "内嵌璇玑·玉衡、千问等先进大模型，一体化体验。",
        icon: Package,
      },
    ],
    []
  );

  return (
    <div className="relative min-h-screen">
      {/* 背景：渐变 + 网格 + 光斑 */}
      <div className="absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-sky-50 via-white to-indigo-50" />
        <svg className="absolute inset-0 h-full w-full opacity-[0.18]">
          <defs>
            <pattern id="grid" width="28" height="28" patternUnits="userSpaceOnUse">
              <path d="M28 0H0V28" fill="none" stroke="#c7d2fe" strokeWidth="0.6" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#grid)" />
        </svg>
        <div className="absolute -top-24 -left-24 h-96 w-96 rounded-full bg-sky-300/25 blur-3xl" />
        <div className="absolute -bottom-28 -right-28 h-[30rem] w-[30rem] rounded-full bg-indigo-300/25 blur-3xl" />
      </div>

      {/* 主体：两栏，更宽松，垂直居中 */}
      <div className="mx-auto grid min-h-screen max-w-6xl place-items-center px-6 py-10 lg:px-8 lg:py-16">
        <div className="grid w-full grid-cols-1 items-center gap-10 lg:grid-cols-12 lg:gap-12">
          {/* 左列：标题 + 亮点 */}
          <div className="lg:col-span-7">
            <div className="lg:col-span-7 lg:text-center text-center">
              <div className="flex items-center justify-center gap-8">
                <img
                  src={zskj}
                  alt="logo zh"
                  className="h-12 w-auto object-contain"
                />
                <img
                  src={yinyan}
                  alt="logo eagle"
                  className="h-12 w-auto object-contain"
                />
              </div>
           </div>





            {/* 两行逐字，字号更大但行距紧凑 */}
            <h1 className="mt-4 font-extrabold leading-[1.15] text-slate-900 tracking-tight">
              <div className="text-2xl sm:text-3xl lg:text-3xl">
                <TypingBlock
                  speed={75}
                  lines={[
                    "鹰眼打造行业专属超级情报引擎，",
                    "AI让您的企业拥有超凡洞察力！",
                  ]}
                />
              </div>
            </h1>

            {/* 四个亮点 —— 左对齐卡片布局 */}
            <div className="mt-10 grid max-w-2xl grid-cols-1 gap-5 sm:grid-cols-2">
              {features.map((f) => {
                const Icon = f.icon;
                return (
                  <div
                    key={f.title}
                    className="rounded-2xl border bg-white/80 p-6 shadow-sm backdrop-blur transition hover:shadow"
                  >
                    <div className="flex items-start gap-3">
                      {/* 圆形图标容器（左侧） */}
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-sky-100 text-sky-600">
                        <Icon className="h-5 w-5" />
                      </div>

                      {/* 文案（右侧） */}
                      <div className="min-w-0 text-left">
                        <div className="text-[16px] font-semibold text-slate-900">{f.title}</div>
                        <div className="mt-1 text-[13px] leading-relaxed text-slate-600">{f.desc}</div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>{/* 左列闭合 */}

          {/* 右列：玻璃拟态登录卡片 */}
          <div className="lg:col-span-5">
            <div
              className="mx-auto w-full max-w-md rounded-3xl border border-white/40 bg-white/10 p-6 shadow-xl backdrop-blur-xl lg:p-7"
              style={{
                backgroundImage:
                  "linear-gradient(135deg, rgba(255,255,255,0.16), rgba(255,255,255,0.06))",
              }}
            >
              <div className="flex items-center gap-3">
                {/* 真实 LOGO */}
                <div className="flex h-12 w-12 items-center justify-center overflow-hidden rounded-xl">
                  <img src={zh} alt="logo" className="h-full w-full object-contain" />
                </div>
                <div>
                  <div className="text-base font-semibold text-slate-900">
                    中核集团定制化AI大模型情报智能体
                  </div>
                </div>
              </div>

              <button
                onClick={() => navigate("/login")}
                className="mt-5 w-full rounded-2xl bg-slate-900 py-2.5 text-[15px] font-medium text-white transition hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-slate-900 focus:ring-offset-2"
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
          </div>{/* 右列闭合 */}
        </div>
      </div>
    </div>
  );
}
