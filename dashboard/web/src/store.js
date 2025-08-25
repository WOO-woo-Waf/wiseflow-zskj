import { useEffect, useState } from "react"
import PocketBase from "pocketbase"
const pb = new PocketBase(import.meta.env.VITE_PB_BASE)
import { useQuery } from "@tanstack/react-query"

import { create } from "zustand"
import { persist } from "zustand/middleware"
// import axios from "redaxios"
import axios from "axios"
import { nanoid } from "nanoid"

import { formatDate, LOCAL_TIME_OFFSITE } from "./lib/utils"

const DAYS_RANGE = [1, 14]

export const useClientStore = create(
  persist(
    (set, get) => ({
      taskId: "",
      urls: ["https://cyberscoop.com"],
      days: 14,
      workflow_name: "鹰眼AI头条",
      toc: ["参考情报", "基本内容", "相关发声情况", "应对策略"],
      selectedInsight: null,
      comment: "",

      setTaskId: (taskId) => set({ taskId }),
      setUrls: (urls) => set({ urls }),
      countUrls: () => get().urls.filter((url) => url).length,
      selectInsight: (id) => set({ selectedInsight: id }),
      updateToc: (value) => set({ toc: value }),
      updateComment: (value) => set({ comment: value }),
      incr: () => set((state) => ({ days: state.days + 1 > DAYS_RANGE[1] ? DAYS_RANGE[1] : state.days + 1 })),
      decr: () => set((state) => ({ days: state.days - 1 < DAYS_RANGE[0] ? DAYS_RANGE[0] : state.days - 1 })),
      minDays: () => get().days === DAYS_RANGE[0],
      maxDays: () => get().days === DAYS_RANGE[1],
    }),
    {
      version: "0.1.1",
      name: "aw-storage",
      // storage: createJSONStorage(() => sessionStorage), // (optional) by default, 'localStorage' is used
    }
  )
)

/** 登录：先尝试管理员，再尝试普通用户（users 集合） */
export async function login({ username, password }) {
  // 1) 管理员登录
  try {
    const admin = await pb.admins.authWithPassword(username, password);
    // 标记角色
    localStorage.setItem("authRole", "admin");
    return admin;
  } catch (e1) {
    // 2) 普通用户登录（users 集合；PocketBase 标准邮箱密码登录）
    try {
      const user = await pb.collection("users").authWithPassword(username, password);
      localStorage.setItem("authRole", "user");
      return user;
    } catch (e2) {
      // 统一抛出更友好的错误
      const msg =
        (e2?.data && (e2.data.message || e2.data.error)) ||
        e2?.message ||
        e1?.message ||
        "登录失败：请检查账号或密码";
      throw new Error(msg);
    }
  }
}

export function isAuth() {
  return pb.authStore.isValid;
}

export function getAuthRole() {
  return localStorage.getItem("authRole") || "guest";
}

export function isAdmin() {
  return getAuthRole() === "admin";
}

export function isUser() {
  return getAuthRole() === "user";
}

/** 退出登录：清理 PB 会话与角色标记 */
export function logout() {
  try {
    pb.authStore.clear();
    localStorage.removeItem("authRole");
    // 如需清理你的 zustand 持久化，可在此追加：
    // useClientStore.persist.clearStorage();
  } catch {}
}

/** 创建新用户（users 集合）：email + password */
export async function registerUser({ email, password }) {
  // PB 的标准字段：email, password, passwordConfirm
  const body = { email, password, passwordConfirm: password };
  const rec = await pb.collection("users").create(body);
  // 如需发验证邮件可以启用（PB 默认提供）：
  // await pb.collection("users").requestVerification(email);
  return rec;
}


// 通用 CRUD（如果你已加过 listAll/createOne/deleteOne 可复用）
export function listAll(collection, { sort = "-created", filter } = {}) {
  return pb.collection(collection).getFullList({ sort, ...(filter ? { filter } : {}) });
}
export function createOne(collection, body) {
  return pb.collection(collection).create(body);
}
export function updateOne(collection, id, body) {
  return pb.collection(collection).update(id, body);
}
export function deleteOne(collection, id) {
  return pb.collection(collection).delete(id);
}

// ---- Sites ----
export function useSites() {
  return useQuery({ queryKey: ["sites"], queryFn: () => listAll("sites") });
}
export const addSite = ({ url, per_hours, within_days, activated = true, category = "" }) =>
  createOne("sites", { url, per_hours, within_days, activated, category });
export const saveSite = (id, body) => updateOne("sites", id, body);
export const removeSite = (id) => deleteOne("sites", id);

/** ---------- Tags ---------- **/
export function useTags() {
  return useQuery({ queryKey: ["tags"], queryFn: () => listAll("tags") });
}

// 新增标签：name 必填，其余给默认值
export const addTag = ({ name, activated = true, explaination = "" }) =>
  createOne("tags", { name, activated, explaination });

// 更新标签：按需传入要改的字段
export const saveTag = (id, body) => updateOne("tags", id, body);

// 删除
export const removeTag = (id) => deleteOne("tags", id);



export function useData(task_id, autoRefetch = undefined) {
  let interval = parseInt(autoRefetch) >= 1000 ? parseInt(autoRefetch) : undefined

  return useQuery({
    queryKey: ["data", task_id ? task_id : ""],
    queryFn: () => data(task_id ? task_id : ""),
    refetchInterval: (query) => {
      //console.log(query)
      if (!query.state.data || (query.state.data && query.state.data.working)) {
        return interval
      }
      return undefined
    },
  })
}

export function createTask({ id, urls, days }) {
  let from = new Date()
  from.setHours(0, 0, 0, 0)
  from.setDate(from.getDate() - days)

  let fromStr = from.toISOString().slice(0, 10).split("-").join("")
  let task_id = id || nanoid(10)
  console.log("creating task: ", task_id, urls.filter((url) => url).length + " sites", fromStr)

  if (urls.length == 0) {
    urls.push("")
  }

  return axios({
    method: "post",
    url: `${import.meta.env.VITE_API_BASE}/sites`,
    headers: {
      "Content-Type": "application/json",
    },
    data: {
      after: fromStr,
      sites: urls,
      task_id: task_id,
    },
  })
    .then(function (response) {
      useClientStore.getState().setTaskId(task_id)
      return response
    })
    .catch(function (error) {
      useClientStore.getState().setTaskId("")
      return error
    })
}

/** ---------- Tokens 消费 读取与聚合 ---------- **/

// 读取 tokens_consume（可选时间窗）
export function getTokensConsume({ from, to } = {}) {
  const filters = [];
  if (from) filters.push(`created >= "${from}"`);
  if (to)   filters.push(`created < "${to}"`);
  const filter = filters.join(" && ");

  return pb.collection("tokens_consume").getFullList({
    sort: "-created",
    ...(filter ? { filter } : {}),
    // 可加 fields 精简：fields: "id,created,model,purpose,total_tokens"
  });
}

export function calcTokensTotal(items = []) {
  return items.reduce((sum, it) => sum + Number(it.total_tokens || 0), 0);
}

export function useTokensConsume(opts = {}) {
  return useQuery({
    queryKey: ["tokens_consume", opts],
    queryFn: () => getTokensConsume(opts),
  });
}



// 首次生成：POST /report/generate
export function generateReport({ insight_id, toc, insight_ids }) {
  return axios({
    method: "post",
    url: `${import.meta.env.VITE_API_BASE}/report/generate`,
    headers: { "Content-Type": "application/json" },
    data: {
      insight_id,
      toc,         // 例如 ["自定义标题"]；留 [""] 走后端默认
      insight_ids, // 可选：多选/合并生成
    },
  }).then((res) => res.data);
}

// 基于记忆追加修改：POST /report/revise
export function reviseReport({ insight_id, comment, memory_id, insight_ids_for_footer }) {
  return axios({
    method: "post",
    url: `${import.meta.env.VITE_API_BASE}/report/revise`,
    headers: { "Content-Type": "application/json" },
    data: {
      insight_id,
      comment,                 // 必填
      memory_id,               // ★ 必填：选中的 report_memories.id
      insight_ids_for_footer,  // 可选：让后端重拉附录/链接
    },
  }).then((res) => res.data);
}

// 清除记忆：POST /report/clear_memory
export function clearReportMemory({ insight_id, clear_all = false }) {
  return axios({
    method: "post",
    url: `${import.meta.env.VITE_API_BASE}/report/clear_memory`,
    headers: { "Content-Type": "application/json" },
    data: {
      insight_id, // 传则清这个任务；不传且 clear_all=true → 清全部
      clear_all,
    },
  });
}

// 直接从 PB 读取某锚点的历史报告（按更新时间倒序）
export function getReportMemoriesPB() {
  return pb.collection("report_memories").getFullList({
    sort: "-updated",
  });
}

const PB_BASE = (import.meta.env.VITE_PB_BASE || "").replace(/\/+$/, "");

// 统一按你的“完美URL”规则拼链接；withToken 可按需开启
export function buildPBFileUrl(record, withToken = false) {
  if (!record?.docx) return "";
  const coll = record.collectionName || "report_memories"; // 兜底集合名
  const url = `${PB_BASE}/api/files/${coll}/${record.id}/${encodeURIComponent(
    record.docx
  )}`;
  return withToken && pb?.authStore?.token ? `${url}?token=${pb.authStore.token}` : url;
}

// 过滤字符串里的双引号（便于 getFirstListItem 过滤）
function escQuotes(s = "") {
  return String(s).replace(/"/g, '\\"');
}

/**
 * A. 按 docx 文件名解析一条 report_memories 记录并给出下载链接
 * @param {string} docxName 例如 "中核日报（2025-08-18）.docx"
 * @param {object} opts 可选过滤条件，如 { titleHint }
 * @returns {Promise<{record, url}>}
 */
export async function resolveMemoryByDocx(docxName, opts = {}) {
  if (!docxName) return { record: null, url: "" };

  // 先尝试精确匹配 docx；必要时可叠加 title 条件，避免重名
  const filter = [
    `docx="${escQuotes(docxName)}"`,
    opts.titleHint ? `title~"${escQuotes(opts.titleHint)}"` : "",
  ]
    .filter(Boolean)
    .join(" && ");

  // getFirstListItem 会按 filter 找到第一条；我们再按 -updated 拿最新的
  const rec = await pb
    .collection("report_memories")
    .getFirstListItem(filter, {
      fields: "id,title,docx,created,updated,collectionId,collectionName",
      sort: "-updated",
    })
    .catch(() => null);

  if (!rec) return { record: null, url: "" };
  return { record: rec, url: buildPBFileUrl(rec) };
}

/**
 * B. 获取最新的一条 report_memories 记录并给出下载链接
 * @returns {Promise<{record, url}>}
 */
export async function resolveLatestMemory() {
  const page = await pb.collection("report_memories").getList(1, 1, {
    sort: "-updated",
    fields: "id,title,docx,created,updated,collectionId,collectionName",
  });
  const rec = page?.items?.[0] || null;
  return { record: rec, url: rec ? buildPBFileUrl(rec) : "" };
}


export function more({ insight_id }) {
  return axios({
    method: "post",
    url: `${import.meta.env.VITE_API_BASE}/search_for_insight`,
    headers: {
      "Content-Type": "application/json",
    },
    data: {
      //toc: toc,
      insight_id: insight_id,
      //comment: comment,
    },
  })
}

export function translations({ article_ids }) {
  return axios({
    method: "post",
    url: `${import.meta.env.VITE_API_BASE}/translations`,
    headers: {
      "Content-Type": "application/json",
    },
    data: {
      article_ids,
    },
  })
}

export function useArticles(date) {
  return useQuery({
    queryKey: ["articles", date],
    queryFn: () => getArticles(date),
  })
}

export function useInsight(id) {
  return useQuery({
    queryKey: ["insight", id],
    queryFn: () => getInsight(id),
  })
}

export function useInsights(date) {
  const { data = [] } = useQuery({
    queryKey: ["insights", date],
    queryFn: () => getInsights(date),
  })
  return data
}

export function useInsightDates() {
  const { data = [] } = useQuery({
    queryKey: ["insight_dates"],
    queryFn: getInsightDates,
  })
  return data
}

export function useArticleDates() {
  return useQuery({
    queryKey: ["article_dates"],
    queryFn: () => getArticleDates(),
  })
}

export function useDatePager(dates) {
  const [index, setIndex] = useState(-1)

  useEffect(() => {
    if (index < 0 && dates) {
      setIndex(dates.length - 1)
    }
  }, [index, dates])

  const hasLast = () => index > 0
  const hasNext = () => index >= 0 && index < dates.length - 1
  const last = () => hasLast() && setIndex(index - 1)
  const next = () => hasNext() && setIndex(index + 1)

  return {
    index,
    last,
    next,
    hasLast,
    hasNext,
  }
}

export function getArticles(date) {
  if (!date) return []

  const from = formatDate(date)
  //const to = formatDate(new Date(new Date(date + "T00:00:00" + LOCAL_TIME_OFFSITE).getTime() + 60 * 60 * 24 * 1000))
  const to = formatDate(new Date(new Date(date + "T00:00:00").getTime() + 60 * 60 * 24 * 1000))
  console.log("from/to", from, to)
  return pb.collection("articles").getFullList({
    sort: "-created",
    expand: "translation_result",
    filter: 'created >= "' + from + '" && created < "' + to + '"',
  })
}

export function getInsight(id) {
  return pb.collection("insights").getOne(id, { expand: "docx" })
}

export function getInsights(date) {
  if (!date) return []

  const from = formatDate(date)
  //const to = formatDate(new Date(new Date(date + "T00:00:00" + LOCAL_TIME_OFFSITE).getTime() + 60 * 60 * 24 * 1000))
  const to = formatDate(new Date(new Date(date + "T00:00:00").getTime() + 60 * 60 * 24 * 1000))
  //  console.log("from/to", from, to)

  const f = 'created >= "' + from + '" && created < "' + to + '"'
  // console.log(f)
  return pb.collection("insights").getFullList({
    sort: "-created",
    expand: "articles, articles.translation_result",
    // expand: "articles",
    filter: f,
  })
}

export async function getInsightDates() {
  const { data } = await axios({
    method: "get",
    url: `${import.meta.env.VITE_PB_BASE}/insight_dates`,
    headers: {
      "Content-Type": "application/json",
      Authorization: "Bearer " + pb.authStore?.token,
    },
  })
  //return data.map((d) => new Date(d + "T00:00:00" + LOCAL_TIME_OFFSITE).toISOString().slice(0, 10))
  return data
}

export async function getArticleDates() {
  let { data } = await axios({
    method: "get",
    url: `${import.meta.env.VITE_PB_BASE}/article_dates`,
    headers: {
      "Content-Type": "application/json",
      Authorization: "Bearer " + pb.authStore?.token,
    },
  })
  //return data.map((d) => new Date(d + "T00:00:00" + LOCAL_TIME_OFFSITE).toISOString().slice(0, 10))
  return data
}

export function unlinkArticle({ insight_id, article_id }) {
  return pb.collection("insights").update(insight_id, {
    "articles-": article_id,
  })
}

export function formatUtcPlus8(iso) {
  if (!iso) return "-";
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return iso;
  const d = new Date(ms + 8 * 60 * 60 * 1000);
  const pad = (n) => String(n).padStart(2, "0");
  const Y = d.getUTCFullYear();
  const M = pad(d.getUTCMonth() + 1);
  const D = pad(d.getUTCDate());
  const h = pad(d.getUTCHours());
  const m = pad(d.getUTCMinutes());
  const s = pad(d.getUTCSeconds());
  return `${Y}-${M}-${D} ${h}:${m}:${s}`;
}