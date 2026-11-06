import { Alert, Button, Card, Checkbox, Col, Input, InputNumber, Popconfirm, Radio, Row, Space, Table, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { post, put } from "../api/client";
import { useAction, useFetch } from "../components/hooks";
import { fmtMs } from "../components/upload";

type Ev = { item_id: string; kind: string; label?: string | null; judgment?: string | number | null; ref?: string | null; start_ms?: number | null; quote?: string | null };
type Part = { id: string; levels: number[]; modifiers: { label: string; enabled: boolean }[] };
type ItemDef = {
  id: string; name: string; type: string; max: number; applicable_if?: string | null; per?: number; free?: number; award?: number | null;
  awards?: Record<string, number> | null; labels?: string[] | null; distinct_by_label?: boolean; parts?: Part[]; structure_levels?: number[];
  elements?: Record<string, number> | null; levels?: Record<string, number> | null; zero_labels?: string[];
};
type Task = {
  id: string; status: string; evidence: Ev[]; note: string | null; set_name: string; video_asset_id: string | null; props_available: boolean;
  segments: { segment: string; start_ms: number; end_ms: number }[]; objections: { objection_id: string; video_ms: number; text: string }[];
  questions: { question_id: string; text: string }[]; card: { checklist: { id: string; name: string }[]; fixed_script?: { version: string; text: string } | null; glossary: string[]; targeted_points: string[] };
  p2_categories: string[]; dimensions: { id: string; name: string; items: ItemDef[] }[];
};

const LABELS: Record<string, string> = {
  sticker: "贴片", kt_board: "KT 板", herd: "从众", loss_aversion: "损失规避", authority: "权威认同", price_split: "价格拆分",
  direct_answer: "正面回答", advantage: "强调优势", altruistic_close: "利他收尾", wrong_answer: "答错", no_answer: "没回答",
  full: "全对", partial: "部分", zero: "错或没答", hook_invalid: "钩子不实或诱导", accent_downgrade: "主体段口音明显",
  sunk_cost: "沉没成本", attire: "穿着不符合要求", hairstyle: "发型不符合要求", dialect: "方言一处",
};
const OCC_LABELS: Record<string, string[]> = { P1: ["attire", "hairstyle"], P3: ["dialect"] };
const OCC_LABEL: Record<string, string> = { P8: "小动作", P10: "笑场", L3: "演绎错误" };

export function MyTasks() {
  const { data } = useFetch<{ id: string; set_name: string; status: string; submitted_at: string | null; sheet_code: string; evidence_count: number }[]>("/calibration/my-tasks");
  return (
    <>
      <Typography.Title level={4}>我的校准任务</Typography.Title>
      <Typography.Paragraph type="secondary">背对背打分：提交前看不到 AI 结果和其他校准员的打分。打到证据级：计次类条目每看到一次点一次，系统记下视频时间。</Typography.Paragraph>
      <Table rowKey="id" dataSource={data} pagination={false} columns={[
        { title: "金标准集", dataIndex: "set_name" },
        { title: "题单", dataIndex: "sheet_code", render: (c, r) => <Link to={`/calibration/tasks/${r.id}`}>{c}</Link> },
        { title: "状态", dataIndex: "status", render: (s) => (s === "submitted" ? <Tag color="green">已提交</Tag> : <Tag>待打分</Tag>) },
        { title: "已录证据", dataIndex: "evidence_count" },
        { title: "提交时间", dataIndex: "submitted_at", render: (t) => (t ? dayjs(t).format("YYYY-MM-DD HH:mm") : "—") },
      ]} />
    </>
  );
}

export default function CalibrationTask() {
  const { id } = useParams();
  const { data: task, reload } = useFetch<Task>(`/calibration/assignments/${id}`);
  const [ev, setEv] = useState<Ev[]>([]);
  const [note, setNote] = useState("");
  const video = useRef<HTMLVideoElement>(null);
  const act = useAction();
  useEffect(() => {
    if (task) (setEv(task.evidence.map(({ item_id, kind, label, judgment, ref, start_ms, quote }) => ({ item_id, kind, label, judgment, ref, start_ms, quote }))), setNote(task.note ?? ""));
  }, [task]);
  if (!task) return null;
  const done = task.status === "submitted";
  const now = () => Math.round((video.current?.currentTime ?? 0) * 1000);
  const seek = (ms?: number | null) => ms != null && video.current && (video.current.currentTime = ms / 1000);
  const find = (p: (e: Ev) => boolean) => ev.find(p);
  const replace = (p: (e: Ev) => boolean, e: Ev | null) => setEv((xs) => [...xs.filter((x) => !p(x)), ...(e ? [e] : [])]);
  const push = (e: Ev) => setEv((xs) => [...xs, e]);
  const removeAt = (e: Ev) => setEv((xs) => xs.filter((x) => x !== e));

  const counter = (it: ItemDef, label: string, title?: string) => {
    const mine = ev.filter((e) => e.item_id === it.id && e.label === label);
    return (
      <Space key={label} wrap style={{ marginBottom: 4 }}>
        <Button size="small" disabled={done} onClick={() => push({ item_id: it.id, kind: it.type === "T2" ? "instance" : "occurrence", label, judgment: "count", start_ms: now() })}>
          + {title ?? LABELS[label] ?? label}
        </Button>
        {mine.map((e, i) => (
          <Tag key={i} closable={!done} onClose={() => removeAt(e)} onClick={() => seek(e.start_ms)} style={{ cursor: "pointer" }}>{fmtMs(e.start_ms)}</Tag>
        ))}
      </Space>
    );
  };

  const levelPicker = (it: ItemDef, part: Part, single: boolean) => {
    const ref = single ? null : part.id;
    const cur = find((e) => e.item_id === it.id && e.kind === "level" && (e.ref ?? null) === ref);
    return (
      <div key={part.id}>
        {!single && <Typography.Text type="secondary">{part.id === "rhythm" ? "节奏掌控" : part.id === "enthusiasm" ? "热情" : part.id}：</Typography.Text>}
        {part.levels.length > 11 ? (
          <InputNumber disabled={done} min={part.levels[part.levels.length - 1]} max={part.levels[0]} precision={0} addonAfter={`/ ${part.levels[0]} 分`}
            value={typeof cur?.judgment === "number" ? cur.judgment : null}
            onChange={(v) => replace((x) => x.item_id === it.id && x.kind === "level" && (x.ref ?? null) === ref,
              v == null ? null : { item_id: it.id, kind: "level", judgment: v, ref })} />
        ) : (
          <Radio.Group disabled={done} value={cur?.judgment} onChange={(e) => replace((x) => x.item_id === it.id && x.kind === "level" && (x.ref ?? null) === ref,
            { item_id: it.id, kind: "level", judgment: e.target.value, ref })}>
            {part.levels.map((l) => <Radio.Button key={l} value={l}>{l}</Radio.Button>)}
          </Radio.Group>
        )}
        {part.modifiers.filter((m) => m.enabled).map((m) => (
          <Checkbox key={m.label} disabled={done} style={{ marginLeft: 12 }} checked={!!find((x) => x.item_id === it.id && x.label === m.label)}
            onChange={(e) => replace((x) => x.item_id === it.id && x.label === m.label, e.target.checked ? { item_id: it.id, kind: "occurrence", label: m.label, judgment: "count" } : null)}>
            {LABELS[m.label] ?? m.label}
          </Checkbox>
        ))}
      </div>
    );
  };

  const body = (it: ItemDef) => {
    if (it.type === "T5") return <Typography.Text type="secondary">按转写时间戳自动计算每分钟字数，无需打分。</Typography.Text>;
    if (it.type === "T4" && it.id === "S2")
      return (
        <>
          <Typography.Paragraph type="secondary" style={{ whiteSpace: "pre-wrap" }}>
            按固定话术的完成准确程度打分。固定话术{task.card.fixed_script ? `（${task.card.fixed_script.version}）：${task.card.fixed_script.text}` : "：该卖点卡没有固定话术"}
          </Typography.Paragraph>
          {it.parts!.map((p) => levelPicker(it, p, it.parts!.length === 1))}
        </>
      );
    if (it.type === "T4") return it.parts!.map((p) => levelPicker(it, p, it.parts!.length === 1));
    if (it.type === "T1" && OCC_LABELS[it.id]) return OCC_LABELS[it.id].map((l) => counter(it, l));
    if (it.type === "T1") return it.id === "P2" ? task.p2_categories.map((c) => counter(it, c)) : counter(it, OCC_LABEL[it.id] ?? "x", OCC_LABEL[it.id] ?? "记一次");
    if (it.type === "T2") {
      if (it.awards) return Object.keys(it.awards).map((l) => counter(it, l));
      if (it.labels) return it.labels.map((l) => counter(it, l));
      if (it.id === "O1") return task.card.glossary.map((t) => counter(it, t, t));
      if (it.id === "O2") return task.card.targeted_points.map((t) => counter(it, t, t));
      return counter(it, "x", "记一次");
    }
    if (it.type === "T3+T4") {
      const s = find((e) => e.item_id === it.id && e.kind === "level");
      return (
        <>
          <div style={{ marginBottom: 6 }}>讲到且讲对的要点：</div>
          {task.card.checklist.map((p) => {
            const cur = find((e) => e.item_id === it.id && e.kind === "checklist_hit" && e.ref === p.id);
            return (
              <Checkbox key={p.id} disabled={done} checked={cur?.judgment === "count"} onChange={(e) => replace((x) => x.item_id === it.id && x.kind === "checklist_hit" && x.ref === p.id,
                { item_id: it.id, kind: "checklist_hit", ref: p.id, label: p.name, judgment: e.target.checked ? "count" : "not_count" })}>{p.name}</Checkbox>
            );
          })}
          <div style={{ margin: "6px 0" }}>结构：
            <Radio.Group disabled={done} value={s?.judgment} onChange={(e) => replace((x) => x.item_id === it.id && x.kind === "level", { item_id: it.id, kind: "level", ref: "structure", judgment: e.target.value })}>
              {it.structure_levels!.map((l) => <Radio.Button key={l} value={l}>{l}</Radio.Button>)}
            </Radio.Group>
          </div>
          {counter(it, "error", "讲错一处（与条款不符，每处 −5）")}
        </>
      );
    }
    // T6
    const qs = it.id === "S3" ? task.objections.map((o) => ({ ref: o.objection_id, text: o.text, ms: o.video_ms })) : task.questions.map((q) => ({ ref: q.question_id, text: q.text, ms: null }));
    return qs.map((q, i) => (
      <div key={q.ref} style={{ marginBottom: 6 }}>
        <a onClick={() => seek(q.ms ?? task.segments.find((s) => s.segment === `question:${q.ref}`)?.start_ms)}>{i + 1}. {q.text}</a>
        <div>
          {it.elements ? (
            <>
              {Object.keys(it.elements).map((el) => {
                const cur = find((e) => e.item_id === it.id && e.ref === q.ref && e.label === el);
                return (
                  <Checkbox key={el} disabled={done} checked={cur?.judgment === "count"} onChange={(e) => replace((x) => x.item_id === it.id && x.ref === q.ref && x.label === el,
                    { item_id: it.id, kind: "question", ref: q.ref, label: el, judgment: e.target.checked ? "count" : "not_count" })}>{LABELS[el] ?? el}</Checkbox>
                );
              })}
              {(it.zero_labels ?? []).map((z) => {
                const cur = find((e) => e.item_id === it.id && e.ref === q.ref && e.label === z);
                return (
                  <Checkbox key={z} disabled={done} checked={cur?.judgment === "count"} onChange={(e) => replace((x) => x.item_id === it.id && x.ref === q.ref && x.label === z,
                    e.target.checked ? { item_id: it.id, kind: "question", ref: q.ref, label: z, judgment: "count" } : null)}>
                    <span style={{ color: "#cf1322" }}>{LABELS[z] ?? z}</span>
                  </Checkbox>
                );
              })}
            </>
          ) : (
            <Radio.Group disabled={done} value={find((e) => e.item_id === it.id && e.ref === q.ref)?.judgment}
              onChange={(e) => replace((x) => x.item_id === it.id && x.ref === q.ref, { item_id: it.id, kind: "question", ref: q.ref, judgment: e.target.value })}>
              {Object.keys(it.levels!).map((l) => <Radio.Button key={l} value={l}>{LABELS[l] ?? l}</Radio.Button>)}
            </Radio.Group>
          )}
        </div>
      </div>
    ));
  };

  const save = () => act(() => put(`/calibration/assignments/${id}`, { evidence: ev, note }), "已保存");
  return (
    <>
      <Space style={{ marginBottom: 8 }}>
        <Typography.Title level={4} style={{ margin: 0 }}>校准打分 · {task.set_name}</Typography.Title>
        {done ? <Tag color="green">已提交</Tag> : <Tag>待打分</Tag>}
      </Space>
      {done && <Alert type="success" showIcon style={{ marginBottom: 12 }} message="已提交。所有校准员提交后系统汇总金标准，分歧条目由管理员组织裁决。" />}
      <Row gutter={16}>
        <Col span={10}>
          <div style={{ position: "sticky", top: 16 }}>
            {task.video_asset_id ? <video ref={video} src={`/api/media/${task.video_asset_id}`} controls preload="metadata" style={{ width: "100%", background: "#000" }} data-testid="cal-video" />
              : <Alert type="warning" message="视频已删除" />}
            <div style={{ marginTop: 8 }}>
              {task.segments.map((s, i) => (
                <Tag key={s.segment} style={{ cursor: "pointer" }} onClick={() => seek(s.start_ms)}>
                  {s.segment === "main" ? "主体段" : s.segment === "reading" ? "朗读" : `题 ${i}`} {fmtMs(s.start_ms)}
                </Tag>
              ))}
            </div>
            <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
              画面里{task.props_available ? "有" : "没有"}贴片或 KT 板。异议出现时间：{task.objections.map((o) => fmtMs(o.video_ms)).join("、")}。
            </Typography.Paragraph>
            <Input.TextArea rows={3} disabled={done} value={note} onChange={(e) => setNote(e.target.value)} placeholder="备注（可选）" />
            {!done && (
              <Space style={{ marginTop: 8 }}>
                <Button onClick={save}>保存草稿</Button>
                <Popconfirm title="提交后不能再改，确定？" onConfirm={async () => {
                  if ((await save()) !== undefined && (await act(() => post(`/calibration/assignments/${id}/submit`), "已提交")) !== undefined) reload();
                }}>
                  <Button type="primary">提交</Button>
                </Popconfirm>
              </Space>
            )}
          </div>
        </Col>
        <Col span={14}>
          {task.dimensions.map((d) => (
            <Card key={d.id} size="small" title={d.name} style={{ marginBottom: 12 }}>
              {d.items.filter((it) => !(it.applicable_if === "props_available" && !task.props_available)).map((it) => (
                <div key={it.id} data-testid={`item-${it.id}`} style={{ padding: "8px 0", borderBottom: "1px solid #f0f0f0" }}>
                  <Typography.Text strong>{it.id} {it.name}</Typography.Text> <Typography.Text type="secondary">（满分 {it.max}）</Typography.Text>
                  <div style={{ marginTop: 4 }}>{body(it)}</div>
                </div>
              ))}
            </Card>
          ))}
        </Col>
      </Row>
    </>
  );
}
