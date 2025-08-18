import { useEffect, useState } from "react"
import { useLocation } from "wouter"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Files } from "lucide-react"
import { ArticleList } from "@/components/article-list"
import { Button } from "@/components/ui/button"
import { Toaster } from "@/components/ui/toaster"
import { ButtonLoading } from "@/components/ui/button-loading"
import { useToast } from "@/components/ui/use-toast"
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import { useClientStore, useInsights, unlinkArticle, useInsightDates, useDatePager, more } from "@/store"

function List({ insights, selected, selectedIds, onToggleSelect, onOpen, onDelete, onReport, onMore, isGettingMore, error }) {
  function change(value) {
    if (value) onOpen(value)
  }

  function unlink(article_id) {
    onDelete(selected, article_id)
  }

  return (
    <Accordion type='single' collapsible onValueChange={change} className='w-full'>
      {insights.map((insight, i) => (
        <AccordionItem value={insight.id} key={i}>
          <AccordionTrigger className='hover:no-underline'>
            <div className='px-4 py-2 cursor-pointer flex items-center gap-2 overflow-hidden'>
              {/* 勾选框（阻止冒泡，避免展开/收起） */}
              <input
                type='checkbox'
                checked={selectedIds.includes(insight.id)}
                onClick={(e) => e.stopPropagation()}
                onChange={(e) => {
                  e.stopPropagation()
                  onToggleSelect(insight.id, e.target.checked)
                }}
              />
              {selected === insight.id && <div className='-ml-4 w-2 h-2 bg-green-400 rounded-full'></div>}
              <p className={"truncate text-wrap text-left flex-1 " + (selected === insight.id ? "font-bold" : "font-normal")}>{insight.content}</p>
              <div className='flex items-center justify-center gap-1'>
                <Files className='h-4 w-4 text-slate-400' />
                <span className='text-slate-400 text-sm leading-none'>x {insight.expand.articles.length}</span>
              </div>
            </div>
          </AccordionTrigger>
          <AccordionContent className='px-4'>
            <ArticleList data={insight.expand.articles} showActions={true} onDelete={unlink} />
            {error && <p className='text-red-500 my-4'>{error.message}</p>}

            {(isGettingMore && <ButtonLoading />) || (
              <div className='flex gap-4 justify-center'>
                <Button onClick={onReport} className='my-4'>
                  生成报告
                </Button>
                {/* <Button variant='outline' onClick={onMore} className='my-4'>
                  搜索更多
                </Button> */}
              </div>
            )}
          </AccordionContent>
        </AccordionItem>
      ))}
    </Accordion>
  )
}

function InsightsScreen({}) {
  const [selectedIds, setSelectedIds] = useState([])
  const selectedInsight = useClientStore((state) => state.selectedInsight)
  const selectInsight = useClientStore((state) => state.selectInsight)
  const dates = useInsightDates()
  const { index, last, next, hasLast, hasNext } = useDatePager(dates)
  const currentDate = dates.length > 0 && index >= 0 ? dates[index] : ""
  const data = useInsights(currentDate)
  const [, navigate] = useLocation()
  const queryClient = useQueryClient()

  const mut = useMutation({
    mutationFn: (params) => {
      if (params && selectedInsight && data.find((insight) => insight.id == selectedInsight).expand.articles.length == 1) {
        throw new Error("不能删除最后一篇文章")
      }
      return unlinkArticle(params)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["insights", currentDate] })
    },
  })

  const mutMore = useMutation({
    mutationFn: (data) => {
      return more(data)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["insights", currentDate] })
    },
  })

  const { toast } = useToast()
  const queryCache = queryClient.getQueryCache()
  queryCache.onError = (error) => {
    console.log("error in cache", error)
    toast({
      variant: "destructive",
      title: "出错啦！",
      description: error.message,
    })
  }

  useEffect(() => {
    selectInsight(null)
    setSelectedIds([]) // 切换日期时清空勾选
  }, [index])

  useEffect(() => {
    mut.reset() // 仅在当前选中项上显示错误
  }, [selectedInsight])

  function unlink(insight_id, article_id) {
    mut.mutate({ insight_id, article_id })
  }

  function report() {
    navigate("/report/" + selectedInsight)
  }

  function getMore() {
    mutMore.mutate({ insight_id: selectedInsight })
  }

  // 勾选切换
  function onToggleSelect(id, checked) {
    setSelectedIds((prev) => {
      if (checked) return prev.includes(id) ? prev : [...prev, id]
      return prev.filter((x) => x !== id)
    })
  }

  // 生成“勾选报告”：与单条一致的路由，带 ?ids=
  function reportSelected() {
    if (!selectedIds.length) {
      toast({ title: "请选择洞见", description: "请先勾选至少一条洞见", variant: "destructive" })
      return
    }
    const anchor = selectedIds[0]
    const qs = `?ids=${encodeURIComponent(selectedIds.join(","))}`
    navigate(`/report/${anchor}${qs}`)
  }

  // 生成“当天报告”：把当日全部洞见打包
  function reportToday() {
    const ids = (data || []).map((i) => i.id)
    if (!ids.length) {
      toast({ title: "暂无数据", description: "当前日期没有洞见", variant: "destructive" })
      return
    }
    const anchor = ids[0]
    const qs = `?ids=${encodeURIComponent(ids.join(","))}`
    navigate(`/report/${anchor}${qs}`)
  }

  return (
    <>
      <h2>分析结果</h2>
      {currentDate && (
        <div className='my-6 flex gap-4 flex items-center'>
          <Button disabled={!hasLast()} variant='outline' onClick={last}>
            &lt;
          </Button>
          <p>{currentDate}</p>
          <Button disabled={!hasNext()} variant='outline' onClick={next}>
            &gt;
          </Button>
        </div>
      )}

      {/* 新增两个按钮 */}
      <div className='mb-4 flex gap-3 items-center'>
        <Button variant='default' onClick={reportToday}>生成当天报告</Button>
        <Button variant='outline' onClick={reportSelected}>生成勾选报告</Button>
        <span className='text-sm text-slate-500'>已选 {selectedIds.length} 条</span>
      </div>

      {data && (
        <div className='grid w-full gap-1.5'>
          <div className='flex gap-2 items-center'>
            <div className='flex-1'>
              <p className=''>选择一项结果生成文档，或勾选多项后点击上方按钮生成合并报告</p>
            </div>
          </div>
          <div className='w-full gap-1.5'>
            <div className=''>
              <List
                insights={data}
                selected={selectedInsight}
                selectedIds={selectedIds}
                onToggleSelect={onToggleSelect}
                onOpen={(id) => selectInsight(id)}
                onDelete={unlink}
                onReport={report}
                onMore={getMore}
                isGettingMore={mutMore.isPending}
                error={mut.error}
              />
            </div>
            <p className='text-sm text-muted-foreground mt-4'>共{Object.keys(data).length}条结果</p>
          </div>
        </div>
      )}
      <div className='my-6 flex flex-col gap-4 w-36 text-left'>
        <Button variant='outline' onClick={() => navigate("/articles")}>
          查看所有文章
        </Button>
        <a href={`${import.meta.env.VITE_PB_BASE}/_/`} target='__blank' className='text-sm underline'>
          数据库管理 &gt;
        </a>
      </div>
      <Toaster />
    </>
  )
}

export default InsightsScreen
