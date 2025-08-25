// src/components/layout/Navbar.jsx
import { NavLink, useNavigate } from "react-router-dom";
import { useState } from "react";
import { isAuth, isAdmin, logout } from "@/store";
import { Button } from "@/components/ui/button";
// 导入 Logo 图片
import logo from "@/assets/logo.jpg";

const links = [
  { to: "/insights", label: "行业洞察" },
  { to: "/articles", label: "最新内容" },
  { to: "/report", label: "生成报告" },
  { to: "/tokens", label: "Tokens 消费" },
  { to: "/sources", label: "信息源管理" },      
];

export default function Navbar() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate("/login", { replace: true });
  };

  const linkClass = ({ isActive }) =>
    "px-3 py-2 rounded-md " + (isActive ? "font-bold underline" : "");

  return (
    <header className="navbar">
      <div className="navbar__inner flex items-center justify-between">
        {/* 品牌 + Logo */}
        <div className="navbar__brand flex items-center gap-2">
          <NavLink to="/" className="flex items-center gap-2">
            <img
              src={logo}
              alt="Logo"
              className="h-36 w-auto object-contain" 
              // h-8 = 2rem 高度（大约 32px）
              // w-auto = 宽度自适应
              // max-h-8 避免撑开
              // object-contain 保持比例
            />
          </NavLink>
        </div>

        <nav className={"navbar__links " + (open ? "is-open" : "")}>
          {links.map((l) => (
            <NavLink key={l.to} to={l.to} className={linkClass} onClick={() => setOpen(false)}>
              {l.label}
            </NavLink>
          ))}

          {/* PB 控制台外链按钮 */}
          <Button asChild variant="outline" size="sm" className="ml-2">
            <a href={`${import.meta.env.VITE_PB_BASE}/_/`} target="__blank" rel="noreferrer">
              数据库管理
            </a>
          </Button>

          {isAuth() && (
            <button className="px-3 py-2" onClick={handleLogout}>
              退出登录
            </button>
          )}
          {isAuth() && (
            <span className="text-sm opacity-70 ml-2">
              {isAdmin() ? "管理员" : "普通用户"}
            </span>
          )}
        </nav>

        <button className="navbar__toggle" onClick={() => setOpen((v) => !v)} aria-label="菜单">
          ☰
        </button>
      </div>
    </header>
  );
}
