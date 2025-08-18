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
      workflow_name: "情报分析",
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

export function login({ username, password }) {
  //return pb.collection("users").authWithPassword(username, password)
  return pb.admins.authWithPassword(username, password)
}

export function isAuth() {
  return pb.authStore.isValid
}

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
