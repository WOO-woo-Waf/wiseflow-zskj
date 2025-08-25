import { useEffect, useMemo, useState } from "react"
import { Button } from "@/components/ui/button"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { ButtonLoading } from "@/components/ui/button-loading"
import { useDatePager, useArticleDates, useArticles, useTags, translations } from "@/store"
import { useNavigate } from "react-router-dom"

// ---------- 工具方法 ----------
function parsePublishTime(ymd) {
  if (!ymd) return null
  const s = String(ymd).trim()
  if (!/^\d{8}$/.test(s)) return null
  const y = Number(s.slice(0, 4))
  const m = Number(s.slice(4, 6)) - 1
  const d = Number(s.slice(6, 8))
  const dt = new Date(Date.UTC(y, m, d))
  return isNaN(dt.getTime()) ? null : dt
}
function formatPublishTime(ymd) {
  const dt = parsePublishTime(ymd)
  if (!dt) return "N/A"
  const y = dt.getUTCFullYear()
  const m = String(dt.getUTCMonth() + 1).padStart(2, "0")
  const d = String(dt.getUTCDate()).padStart(2, "0")
  return `${y}-${m}-${d}`
}
function dateInputToYmdNum(s) {
  if (!s) return null
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})$/)
  if (!m) return null
  return Number(`${m[1]}${m[2]}${m[3]}`)
}
// 文章 tag 字段 → id 数组
function normalizeTagIds(tagField) {
  if (tagField == null) return []
  if (Array.isArray(tagField)) return tagField.filter(Boolean).map(String)
  return [String(tagField)]
}

export default function ArticlesScreen() {
  const navigate = useNavigate()

  // 原有文章查询
  const queryDates = useArticleDates()
  const { index, last, next, hasLast, hasNext } = useDatePager(queryDates.data)
  const currentDate = queryDates.data && index >= 0 ? queryDates.data[index] : ""
  const query = useArticles(currentDate)
  const queryClient = useQueryClient()

  // 翻译
  const mut = useMutation({
    mutationFn: (data) => translations(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["articles", currentDate] })
    },
  })

  // ====== 时间筛选 ======
  const [startDate, setStartDate] = useState("")
  const [endDate, setEndDate] = useState("")
  const [filterActive, setFilterActive] = useState(false)

  // ====== 标签数据（来自 store） ======
  const tagsQuery = useTags()
  const tagIdToName = useMemo(() => {
    const map = new Map()
    ;(tagsQuery.data || []).forEach((t) => {
      map.set(String(t.id), String(t.name ?? t.id))
    })
    return map
  }, [tagsQuery.data])

  const [selectedTagIds, setSelectedTagIds] = useState([])

  const allTagItems = useMemo(() => {
    const items = (tagsQuery.data || []).map((t) => ({ id: String(t.id), name: String(t.name ?? t.id) }))
    return items.sort((a, b) => a.name.localeCompare(b.name, "zh-Hans-CN"))
  }, [tagsQuery.data])

  // ====== 过滤逻辑 ======
  const filteredData = useMemo(() => {
    const list = query.data || []
    const sorted = [...list].sort(
      (a, b) => Number(b.publish_time || 0) - Number(a.publish_time || 0)
    )

    // 时间
    let byTime = sorted
    if (filterActive) {
      const start = dateInputToYmdNum(startDate)
      const end = dateInputToYmdNum(endDate)
      byTime = sorted.filter((a) => {
        const pt = Number(a.publish_time || 0)
        if (!pt) return false
        if (start && pt < start) return false
        if (end && pt > end) return false
        return true
      })
    }

    // 标签
    if (selectedTagIds.length === 0) return byTime
    return byTime.filter((a) => {
      const ids = normalizeTagIds(a.tag)
      return ids.some((id) => selectedTagIds.includes(String(id)))
    })
  }, [query.data, filterActive, startDate, endDate, selectedTagIds])

  // 换页时清空筛选
  useEffect(() => {
    setFilterActive(false)
    setStartDate("")
    setEndDate("")
    setSelectedTagIds([])
  }, [currentDate])

  return (
    <>
      <h2>文章</h2>

      {/* 顶部操作 */}
      <div className="my-6 flex gap-4 w-fit items-center">
        <Button onClick={() => navigate("/insights")}>查看分析结果</Button>
        {mut.isPending ? <ButtonLoading /> : (query.data && query.data.length > 0)}
      </div>

      {/* 日期翻页器 */}
      {!filterActive && currentDate && (
        <div className="my-4 flex gap-4 items-center">
          <Button disabled={!hasLast()} variant="outline" onClick={last}>&lt;</Button>
          <p>{currentDate}</p>
          <Button disabled={!hasNext()} variant="outline" onClick={next}>&gt;</Button>
        </div>
      )}

      {/* 时间筛选 */}
      <div className="my-6 p-4 border rounded-lg flex flex-col md:flex-row gap-3 md:items-end">
        <div className="flex flex-col">
          <label className="text-sm text-gray-500 mb-1">开始发布日期</label>
          <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="border rounded px-3 py-2" />
        </div>
        <div className="flex flex-col">
          <label className="text-sm text-gray-500 mb-1">结束发布日期</label>
          <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="border rounded px-3 py-2" />
        </div>
        <div className="flex gap-2 md:ml-auto">
          <Button onClick={() => setFilterActive(true)} disabled={!startDate && !endDate}>按发布时间筛选</Button>
          <Button variant="outline" onClick={() => { setFilterActive(false); setStartDate(""); setEndDate("") }}>清除时间筛选</Button>
        </div>
      </div>

      {/* 标签筛选 */}
      <div className="mt-4 p-4 border rounded-lg">
        <div className="flex items-center justify-between">
          <div className="font-medium">按标签筛选</div>
          <div className="text-sm text-gray-500">{tagsQuery.isLoading ? "加载标签…" : `可选 ${allTagItems.length} 个`}</div>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {allTagItems.map((t) => {
            const active = selectedTagIds.includes(t.id)
            return (
              <button
                key={t.id}
                type="button"
                onClick={() =>
                  setSelectedTagIds((prev) =>
                    prev.includes(t.id) ? prev.filter((x) => x !== t.id) : [...prev, t.id]
                  )
                }
                className={[
                  "px-3 py-1 rounded-full border text-sm transition",
                  active ? "bg-blue-600 text-white border-blue-600" : "bg-gray-50 text-gray-700 border-gray-200 hover:bg-gray-100"
                ].join(" ")}
              >
                {t.name}
              </button>
            )
          })}
        </div>
        {selectedTagIds.length > 0 && (
          <div className="mt-3 flex items-center gap-3">
            <span className="text-sm text-gray-600">
              已选：{selectedTagIds.map((id) => tagIdToName.get(id) || id).join("、")}
            </span>
            <Button size="sm" variant="outline" onClick={() => setSelectedTagIds([])}>清除标签</Button>
          </div>
        )}
      </div>

      {/* 列表 */}
      <div className="mt-4 text-sm text-gray-500">共 {filteredData?.length || 0} 篇</div>
      <div className="grid gap-4 mt-4">
        {filteredData?.map((a) => {
          const publishLabel = formatPublishTime(a.publish_time)
          const tagNames = normalizeTagIds(a.tag).map((id) => tagIdToName.get(id) || id)
          return (
            <div key={a.id ?? a.url ?? publishLabel} className="border rounded-lg p-4 hover:shadow-sm transition">
              <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-2">
                <h3 className="text-lg font-medium line-clamp-1">{a.title || a.url || "未命名文章"}</h3>
                <span className="text-sm text-gray-500">发布时间：{publishLabel}</span>
              </div>
              {a.abstract && <p className="mt-2 text-sm text-gray-700 line-clamp-2">{a.abstract}</p>}
              <div className="mt-3 flex flex-wrap gap-2 items-center">
                {a.url && <a href={a.url} target="_blank" rel="noreferrer" className="text-blue-600 text-sm underline">查看原文</a>}
                {tagNames.map((name) => (
                  <span key={name} className="text-xs px-2 py-1 rounded-full bg-gray-100 text-gray-600 border">{name}</span>
                ))}
              </div>
            </div>
          )
        })}
      </div>

      <div className="my-6 flex gap-4">
        <Button onClick={() => navigate("/insights")}>查看分析结果</Button>
      </div>
    </>
  )
}
