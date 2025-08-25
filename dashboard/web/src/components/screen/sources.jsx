// src/components/screen/sources.jsx
import { useState } from "react";
import { useQueryClient, useMutation } from "@tanstack/react-query";
import {
  useSites, saveSite, removeSite, addSite,
  useTags, saveTag, removeTag, addTag
} from "@/store";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";

/* -------- Sites 行 -------- */
function EditableSiteRow({ s, onSave, onDelete }) {
  const [form, setForm] = useState({
    url: s.url || "",
    per_hours: s.per_hours ?? 24,
    within_days: s.within_days ?? 14,
    activated: !!s.activated,
    category: s.category || "",
  });
  const [editing, setEditing] = useState(false);
  const change = (k, v) => setForm((p) => ({ ...p, [k]: v }));

  return (
    <div className="grid grid-cols-6 gap-2 items-center px-3 py-2 border-b">
      <div className="truncate">
        {editing ? <Input value={form.url} onChange={(e) => change("url", e.target.value)} /> : <span title={s.url}>{s.url}</span>}
      </div>
      <div>{editing ? <Input type="number" value={form.per_hours} onChange={(e) => change("per_hours", Number(e.target.value))} /> : s.per_hours}</div>
      <div>{editing ? <Input type="number" value={form.within_days} onChange={(e) => change("within_days", Number(e.target.value))} /> : s.within_days}</div>
      <label className="flex items-center gap-2">
        <input disabled={!editing} type="checkbox" checked={editing ? form.activated : !!s.activated} onChange={(e) => change("activated", e.target.checked)} />
        {editing ? (form.activated ? "启用" : "停用") : s.activated ? "启用" : "停用"}
      </label>
      <div>{editing ? <Input value={form.category} onChange={(e) => change("category", e.target.value)} /> : (s.category || "-")}</div>
      <div className="text-right flex gap-2 justify-end">
        {editing ? (
          <>
            <Button size="sm" onClick={() => onSave(s.id, form).then(() => setEditing(false))}>保存</Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>取消</Button>
          </>
        ) : (
          <>
            <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>编辑</Button>
            <Button size="sm" variant="ghost" className="text-red-500" onClick={() => onDelete(s.id)}>删除</Button>
          </>
        )}
      </div>
    </div>
  );
}

/* -------- Tags 行（fields: name, activated, explaination） -------- */
function EditableTagRow({ t, onSave, onDelete }) {
  const [form, setForm] = useState({
    name: t.name || "",
    activated: !!t.activated,
    explaination: t.explaination || "",
  });
  const [editing, setEditing] = useState(false);
  const change = (k, v) => setForm((p) => ({ ...p, [k]: v }));

  return (
    <div className="grid grid-cols-5 gap-2 items-center px-3 py-2 border-b">
      <div className="truncate">
        {editing ? <Input value={form.name} onChange={(e) => change("name", e.target.value)} /> : t.name}
      </div>
      <label className="flex items-center gap-2">
        <input disabled={!editing} type="checkbox" checked={editing ? form.activated : !!t.activated} onChange={(e) => change("activated", e.target.checked)} />
        {editing ? (form.activated ? "启用" : "停用") : t.activated ? "启用" : "停用"}
      </label>
      <div className="truncate">
        {editing ? <Input value={form.explaination} onChange={(e) => change("explaination", e.target.value)} /> : (t.explaination || "-")}
      </div>
      <div className="opacity-70">{new Date(t.created).toLocaleString()}</div>
      <div className="text-right flex gap-2 justify-end">
        {editing ? (
          <>
            <Button size="sm" onClick={() => onSave(t.id, form).then(() => setEditing(false))}>保存</Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>取消</Button>
          </>
        ) : (
          <>
            <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>编辑</Button>
            <Button size="sm" variant="ghost" className="text-red-500" onClick={() => onDelete(t.id)}>删除</Button>
          </>
        )}
      </div>
    </div>
  );
}

export default function SourcesScreen() {
  const qc = useQueryClient();

  // sites
  const { data: sites = [], isLoading: sitesLoading } = useSites();
  const saveSiteMut = useMutation({ mutationFn: ({ id, body }) => saveSite(id, body), onSuccess: () => qc.invalidateQueries({ queryKey: ["sites"] }) });
  const delSiteMut = useMutation({ mutationFn: removeSite, onSuccess: () => qc.invalidateQueries({ queryKey: ["sites"] }) });
  const [siteForm, setSiteForm] = useState({ url: "", per_hours: 24, within_days: 14, activated: true, category: "" });
  const addSiteMut = useMutation({ mutationFn: addSite, onSuccess: () => { qc.invalidateQueries({ queryKey: ["sites"] }); setSiteForm({ url: "", per_hours: 24, within_days: 14, activated: true, category: "" }); } });
  const [siteBulk, setSiteBulk] = useState("");

  // tags
  const { data: tags = [], isLoading: tagsLoading } = useTags();
  const saveTagMut = useMutation({ mutationFn: ({ id, body }) => saveTag(id, body), onSuccess: () => qc.invalidateQueries({ queryKey: ["tags"] }) });
  const delTagMut = useMutation({ mutationFn: removeTag, onSuccess: () => qc.invalidateQueries({ queryKey: ["tags"] }) });
  const [tagForm, setTagForm] = useState({ name: "", activated: true, explaination: "" });
  const addTagMut = useMutation({ mutationFn: addTag, onSuccess: () => { qc.invalidateQueries({ queryKey: ["tags"] }); setTagForm({ name: "", activated: true, explaination: "" }); } });
  const [tagBulk, setTagBulk] = useState("");

  const onSaveSite = (id, body) => saveSiteMut.mutateAsync({ id, body });
  const onDeleteSite = (id) => delSiteMut.mutate(id);
  const onSaveTag = (id, body) => saveTagMut.mutateAsync({ id, body });
  const onDeleteTag = (id) => delTagMut.mutate(id);

  const importSites = async () => {
    const lines = siteBulk.split("\n").map(s => s.trim()).filter(Boolean);
    if (!lines.length) return;
    await Promise.all(lines.map(url => addSite({ url, per_hours: siteForm.per_hours, within_days: siteForm.within_days, activated: siteForm.activated, category: siteForm.category })));
    setSiteBulk(""); qc.invalidateQueries({ queryKey: ["sites"] });
  };
  const importTags = async () => {
    const names = tagBulk.split("\n").map(s => s.trim()).filter(Boolean);
    if (!names.length) return;
    await Promise.all(names.map(name => addTag({ name, activated: true, explaination: "" })));
    setTagBulk(""); qc.invalidateQueries({ queryKey: ["tags"] });
  };

  return (
    <div className="space-y-10">
      {/* ---------------- Sites ---------------- */}
      <section>
        <h2 className="text-xl font-semibold mb-2">网站（sites）</h2>

        <div className="border rounded overflow-hidden">
          <div className="grid grid-cols-6 font-semibold bg-gray-50 px-3 py-2 border-b">
            <div>网址</div><div>间隔时长（小时）</div><div>爬取内容时间范围（天）</div><div>状态</div><div>分类</div><div className="text-right">操作</div>
          </div>
          {sitesLoading ? (
            <div className="px-3 py-6 text-sm text-muted-foreground">加载中…</div>
          ) : sites.length ? (
            sites.map((s) => (
              <EditableSiteRow key={s.id} s={s} onSave={(id, body) => onSaveSite(id, body)} onDelete={onDeleteSite} />
            ))
          ) : (
            <div className="px-3 py-6 text-sm text-muted-foreground">暂无数据</div>
          )}
        </div>

        {/* 添加 / 批量导入 */}
        <div className="mt-6 space-y-4">
          <h3 className="font-semibold">添加网站</h3>
          <div className="grid md:grid-cols-4 gap-3">
            <div className="md:col-span-2">
              <Label className="mb-1 block">URL</Label>
              <Input value={siteForm.url} onChange={(e) => setSiteForm((p)=>({ ...p, url: e.target.value }))} placeholder="https://example.com" />
            </div>
            <div>
              <Label className="mb-1 block">per_hours</Label>
              <Input type="number" value={siteForm.per_hours} onChange={(e) => setSiteForm((p)=>({ ...p, per_hours: Number(e.target.value) }))} />
            </div>
            <div>
              <Label className="mb-1 block">within_days</Label>
              <Input type="number" value={siteForm.within_days} onChange={(e) => setSiteForm((p)=>({ ...p, within_days: Number(e.target.value) }))} />
            </div>
            <div>
              <Label className="mb-1 block">分类（可选）</Label>
              <Input value={siteForm.category} onChange={(e) => setSiteForm((p)=>({ ...p, category: e.target.value }))} />
            </div>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={siteForm.activated} onChange={(e)=>setSiteForm((p)=>({ ...p, activated: e.target.checked }))} />
              启用
            </label>
            <div className="md:col-span-4">
              <Button onClick={() => siteForm.url.trim() && addSiteMut.mutate(siteForm)}>添加</Button>
            </div>
          </div>

          <div className="pt-4">
            <h3 className="font-semibold mb-2">批量导入（每行一个 URL）</h3>
            <Textarea rows={8} value={siteBulk} onChange={(e) => setSiteBulk(e.target.value)} placeholder={"https://a.com\nhttps://b.com"} />
            <div className="mt-2">
              <Button variant="secondary" onClick={importSites} disabled={!siteBulk.trim()}>批量导入</Button>
            </div>
          </div>
        </div>
      </section>

      {/* ---------------- Tags ---------------- */}
      <section>
        <h2 className="text-xl font-semibold mb-2">标签 / 关键词（tags）</h2>

        <div className="border rounded overflow-hidden">
          <div className="grid grid-cols-5 font-semibold bg-gray-50 px-3 py-2 border-b">
            <div>名称</div><div>状态</div><div>说明</div><div>创建时间</div><div className="text-right">操作</div>
          </div>
          {tagsLoading ? (
            <div className="px-3 py-6 text-sm text-muted-foreground">加载中…</div>
          ) : tags.length ? (
            tags.map((t) => (
              <EditableTagRow key={t.id} t={t} onSave={(id, body) => onSaveTag(id, body)} onDelete={(id) => onDeleteTag(id)} />
            ))
          ) : (
            <div className="px-3 py-6 text-sm text-muted-foreground">暂无数据</div>
          )}
        </div>

        {/* 添加 / 批量导入 */}
        <div className="mt-6 space-y-4">
          <h3 className="font-semibold">添加标签</h3>
          <div className="grid md:grid-cols-3 gap-3">
            <div>
              <Label className="mb-1 block">名称（name）</Label>
              <Input value={tagForm.name} onChange={(e)=>setTagForm(p=>({ ...p, name: e.target.value }))} placeholder="例如：核能" />
            </div>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={tagForm.activated} onChange={(e)=>setTagForm(p=>({ ...p, activated: e.target.checked }))} />
              启用
            </label>
            <div className="md:col-span-3">
              <Label className="mb-1 block">说明（explaination）</Label>
              <Input value={tagForm.explaination} onChange={(e)=>setTagForm(p=>({ ...p, explaination: e.target.value }))} placeholder="该标签的解释/用途" />
            </div>
            <div className="md:col-span-3">
              <Button onClick={() => tagForm.name.trim() && addTagMut.mutate(tagForm)}>添加</Button>
            </div>
          </div>

          <div className="pt-4">
            <h3 className="font-semibold mb-2">批量导入（每行一个名称）</h3>
            <Textarea rows={8} value={tagBulk} onChange={(e)=>setTagBulk(e.target.value)} placeholder={"核能\n反应堆\n压水堆"} />
            <div className="mt-2">
              <Button variant="secondary" onClick={importTags} disabled={!tagBulk.trim()}>批量导入</Button>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
