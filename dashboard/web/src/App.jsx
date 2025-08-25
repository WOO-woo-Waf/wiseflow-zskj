import "./App.css";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { Toaster } from "@/components/ui/toaster";

import RootLayout from "@/components/layout/RootLayout";
import Steps from "@/components/screen/steps";

import LoginScreen from "@/components/screen/login";
import StartScreen from "@/components/screen/start";
import InsightsScreen from "@/components/screen/insights";
import ArticlesScreen from "@/components/screen/articles";
import ReportScreen from "@/components/screen/report";
import TokensScreen from "@/components/screen/tokens";
import SourcesScreen from "@/components/screen/sources";
import LandingScreen from "@/components/screen/landing";

import { isAuth } from "@/store";

import { Routes, Route, Navigate, Outlet } from "react-router-dom";

const queryClient = new QueryClient();

// 受保护路由
function RequireAuth() {
  return isAuth() ? <Outlet /> : <Navigate to="/landing" replace />;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Routes>
        {/* 公共路由 */}
        <Route path="/" element={<Navigate to="/landing" replace />} />
        <Route path="/landing" element={<LandingScreen />} />   {/* 新增：默认落地页 */}
        <Route path="/login" element={<LoginScreen />} />

        {/* 需要登录的路由：带导航栏 */}
        <Route element={<RequireAuth />}>
          <Route element={<RootLayout />}>
            <Route index element={<Navigate to="/insights" replace />} />
            <Route path="/start" element={<><Steps /><StartScreen /></>} />
            <Route path="/articles" element={<><Steps /><ArticlesScreen /></>} />
            <Route path="/insights" element={<><Steps /><InsightsScreen /></>} />
            <Route path="/report" element={<><Steps /><ReportScreen /></>} />
            <Route path="/report/:insight_id" element={<><Steps /><ReportScreen /></>} />
            <Route path="/tokens" element={<TokensScreen />} />
            <Route path="/sources" element={<SourcesScreen />} />
            <Route path="*" element={<div>404</div>} />
          </Route>
        </Route>
      </Routes>

      <Toaster />
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  );
}
