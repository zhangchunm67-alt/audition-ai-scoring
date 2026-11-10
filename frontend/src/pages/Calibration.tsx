import { Alert, Button, Card, Col, Descriptions, Drawer, Form, Input, InputNumber, Modal, Row, Select, Space, Statistic, Table, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { post, type S } from "../api/client";
import { useAction, useFetch } from "../components/hooks";

type Metrics = {
  samples: number; final: number; pending: number; dimension_agreement: number | null; conclusion_agreement: number | null;
  targets: { dimension: number; conclusion: number; item: number }; gate_passed: boolean;
  items: { item_id: string; name: string; ok: number; n: number; rate: number | null; alert: boolean }[];
  low_confidence_share: number | null; human_dimension_agreement: number | null; human_conclusion_agreement: number | null;
};
type SetRow = { id: string; name: string; purpose: string; note: string | null; created_at: string; rubric_version: string; samples: number; final: number; needs_adjudication: number };
type SampleRow = { id: string; recording_id: string; candidate_name: string; submitted_at: string | null; status: string; flagged_items: string[];
  assignments: { calibrator: string; status: string }[]; gold_total: number | null };
type SetDetail = SetRow & { metrics: Metrics; sample_rows: SampleRow[] };

export const PURPOSE: Record<string, string> = { prelaunch: "上线前金标准", monthly_sample: "月度抽检", regression: "回归" };
const SAMPLE_STATUS: Record<string, [string, string]> = { collecting: ["打分中", "processing"], needs_adjudication: ["待裁决", "orange"], final: ["已定稿", "green"] };
export const pct = (x: number | null | undefined) => (x == null ? "—" : `${(x * 100).toFixed(1)}%`);

export function MetricsCards({ m }: { m: Metrics }) {
  const ok = (v: number | null, t: number) => (v == null ? undefined : { color: v >= t ? "#389e0d" : "#cf1322" });
  return (
    <>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={5}><Statistic title={`维度档位相差 ≤ 1 档（目标 ${pct(m.targets.dimension)}）`} value={pct(m.dimension_agreement)} valueStyle={ok(m.dimension_agreement, m.targets.dimension)} /></Col>
        <Col span={5}><Statistic title={`结论一致（目标 ${pct(m.targets.conclusion)}）`} value={pct(m.conclusion_agreement)} valueStyle={ok(m.conclusion_agreement, m.targets.conclusion)} /></Col>
        <Col span={4}><Statistic title="已定稿 / 样本" value={`${m.final} / ${m.samples}`} /></Col>
        <Col span={5}><Statistic title="人与人：维度 / 结论一致" value={`${pct(m.human_dimension_agreement)} / ${pct(m.human_conclusion_agreement)}`} /></Col>
        <Col span={5}><Statistic title="AI 低置信条目占比" value={pct(m.low_confidence_share)} /></Col>
      </Row>
      {m.final > 0 && (
        <Alert style={{ marginBottom: 16 }} type={m.gate_passed ? "success" : "error"} showIcon
          message={m.gate_passed ? "达到上线门槛（PRD 第 1 节）" : "未达到上线门槛：准确度没达标不上线"} />
      )}
    </>
  );
}

export function ItemRates({ m }: { m: Metrics }) {
  return (
    <Table size="small" rowKey="item_id" pagination={false} dataSource={m.items} columns={[
      { title: "条目", render: (_, r) => r.name },
      { title: "一致（AI 与金标准相差 ≤ 满分 10%）", render: (_, r) => `${r.ok} / ${r.n}` },
      { title: "一致率", dataIndex: "rate", render: (v, r) => <span style={{ color: r.alert ? "#cf1322" : undefined }}>{pct(v)}</span> },
      { title: "", render: (_, r) => (r.alert ? <Tag color="red">低于 {pct(m.targets.item)}，先改该条规则或提示词</Tag> : null) },
    ]} />
  );
}

export default function Calibration() {
  const { data, reload } = useFetch<SetRow[]>("/calibration/sets");
  const rubrics = useFetch<S<"RubricSummary">[]>("/rubrics");
  const act = useAction();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();
  return (
    <>
      <Typography.Title level={4}>金标准与校准</Typography.Title>
      <Typography.Paragraph type="secondary">
        上线前：2–3 位校准员对 20–30 条录像背对背打到证据级，作为金标准集；上线后每月抽 10–20 条核对。校准员之间条目分相差超过满分 20% 的条目需开会裁决。
      </Typography.Paragraph>
      <Button type="primary" style={{ marginBottom: 16 }} onClick={() => setOpen(true)}>新建金标准集</Button>
      <Table<SetRow> rowKey="id" dataSource={data} pagination={false} columns={[
        { title: "名称", dataIndex: "name", render: (n, r) => <Link to={`/calibration/sets/${r.id}`}>{n}</Link> },
        { title: "用途", dataIndex: "purpose", render: (p) => PURPOSE[p] },
        { title: "评分标准", dataIndex: "rubric_version" },
        { title: "样本", render: (_, r) => `${r.final} 已定稿 / ${r.samples}` },
        { title: "待裁决", dataIndex: "needs_adjudication", render: (n) => (n ? <Tag color="orange">{n}</Tag> : "—") },
        { title: "创建时间", dataIndex: "created_at", render: (t) => dayjs(t).format("YYYY-MM-DD") },
      ]} />
      <Modal title="新建金标准集" open={open} onCancel={() => setOpen(false)} onOk={async () => {
        const v = await form.validateFields();
        const r = await act(() => post<SetRow>("/calibration/sets", v), "已创建");
        if (r) (setOpen(false), form.resetFields(), reload(), nav(`/calibration/sets/${r.id}`));
      }}>
        <Form form={form} layout="vertical" initialValues={{ purpose: "prelaunch" }}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input placeholder="如：上线前金标准 / 2026 年 11 月抽检" /></Form.Item>
          <Form.Item name="purpose" label="用途" rules={[{ required: true }]}>
            <Select options={[{ value: "prelaunch", label: "上线前金标准" }, { value: "monthly_sample", label: "月度抽检" }]} />
          </Form.Item>
          <Form.Item name="rubric_version_id" label="评分标准版本" rules={[{ required: true }]} extra="校准员按这个版本打分，与 AI 对比时 AI 也按这个版本计算。">
            <Select options={(rubrics.data ?? []).filter((x) => x.status !== "retired").map((x) => ({ value: x.id, label: x.version }))} />
          </Form.Item>
          <Form.Item name="note" label="备注"><Input /></Form.Item>
        </Form>
      </Modal>
    </>
  );
}

type SampleDetail = SampleRow & {
  adjudication: Record<string, { score: number; note: string }>; gold: { items: Record<string, number>; total_grade: number; grade_pass: boolean } | null;
  ai_report_id: string | null;
  calibrators: { name: string; status: string; items: Record<string, number | null> | null; total_grade: number | null; note: string | null }[];
  comparison: null | { ai_complete: boolean; ai: { total_grade: number; conclusion: string; label: string; critical: boolean; rounds: number } | null;
    items: { item_id: string; name: string; ai: number | null; gold: number | null; max: number; agree: boolean; low_confidence: boolean }[];
    dimensions: { id: string; name: string; ai_grade: number; gold_grade: number; agree: boolean }[]; conclusion_agree: boolean };
};

function SampleDrawer({ id, onClose, onChanged }: { id: string; onClose: () => void; onChanged: () => void }) {
  const { data: d, reload } = useFetch<SampleDetail>(`/calibration/samples/${id}`);
  const act = useAction();
  const [adj] = Form.useForm();
  if (!d) return null;
  const itemIds = d.calibrators[0]?.items ? Object.keys(d.calibrators[0].items) : [];
  return (
    <Drawer title={`样本：${d.candidate_name}`} width={900} open onClose={onClose}>
      <Space style={{ marginBottom: 12 }}>
        <Tag color={SAMPLE_STATUS[d.status][1]}>{SAMPLE_STATUS[d.status][0]}</Tag>
        {d.ai_report_id && <Link to={`/reports/${d.ai_report_id}`}>查看 AI 报告</Link>}
      </Space>
      {d.status === "needs_adjudication" && (
        <Card size="small" title={`待裁决条目：${d.flagged_items.join("、")}（校准员相差超过满分 20%）`} style={{ marginBottom: 12, borderColor: "#fa8c16" }}>
          <Form form={adj} layout="inline" onFinish={async (v) => {
            if (await act(() => post(`/calibration/samples/${id}/adjudicate`, v), "已录入裁决")) (adj.resetFields(), reload(), onChanged());
          }}>
            <Form.Item name="item_id" rules={[{ required: true }]}><Select placeholder="条目" style={{ width: 100 }} options={d.flagged_items.filter((x) => !d.adjudication[x]).map((x) => ({ value: x, label: x }))} /></Form.Item>
            <Form.Item name="score" rules={[{ required: true }]}><InputNumber placeholder="裁决分" min={0} /></Form.Item>
            <Form.Item name="note" rules={[{ required: true }]}><Input placeholder="裁决理由（会议结论）" style={{ width: 260 }} /></Form.Item>
            <Button htmlType="submit" type="primary">录入</Button>
          </Form>
        </Card>
      )}
      {d.comparison && (
        <>
          {!d.comparison.ai_complete && <Alert type="error" showIcon style={{ marginBottom: 12 }} message="AI 结果不完整（按该版本需要更多轮次或缺证据），计为不一致" />}
          {d.comparison.ai && (
            <Descriptions bordered size="small" column={3} style={{ marginBottom: 12 }}>
              <Descriptions.Item label="金标准总档位">{d.gold?.total_grade}（{d.gold?.grade_pass ? "达标" : "不达标"}）</Descriptions.Item>
              <Descriptions.Item label="AI 总档位">{d.comparison.ai.total_grade}（{d.comparison.ai.conclusion === "pass" ? "达标" : "不达标"}，{d.comparison.ai.rounds} 轮）</Descriptions.Item>
              <Descriptions.Item label="结论一致">{d.comparison.conclusion_agree ? <Tag color="green">一致</Tag> : <Tag color="red">不一致</Tag>}</Descriptions.Item>
              {d.comparison.dimensions.map((x) => (
                <Descriptions.Item key={x.id} label={x.name}>金标准 {x.gold_grade} 档 · AI {x.ai_grade} 档 {x.agree ? "" : <Tag color="red">相差超过 1 档</Tag>}</Descriptions.Item>
              ))}
            </Descriptions>
          )}
        </>
      )}
      <Table size="small" rowKey="id" pagination={false} dataSource={itemIds.map((id_) => ({ id: id_ }))} columns={[
        { title: "条目", dataIndex: "id" },
        ...d.calibrators.map((c, i) => ({ title: c.name, key: `c${i}`, render: (_: unknown, r: { id: string }) => c.items?.[r.id] ?? "—" })),
        { title: "金标准", render: (_: unknown, r: { id: string }) => (d.gold ? `${d.gold.items[r.id] ?? "—"}${d.adjudication[r.id] ? "（裁决）" : ""}` : "—") },
        { title: "AI", render: (_: unknown, r: { id: string }) => {
          const it = d.comparison?.items.find((x) => x.item_id === r.id);
          return it ? <span style={{ color: it.agree ? undefined : "#cf1322" }}>{it.ai ?? "—"}{it.low_confidence ? "（低置信）" : ""}</span> : "—";
        } },
      ]} />
    </Drawer>
  );
}

export function CalibrationSet() {
  const { id } = useParams();
  const { data: d, reload } = useFetch<SetDetail>(`/calibration/sets/${id}`);
  const users = useFetch<S<"UserOut">[]>("/users");
  const recs = useFetch<S<"RecordingOut">[]>("/recordings?status=done");
  const act = useAction();
  const [open, setOpen] = useState<string | null>(null);
  const [cals, setCals] = useState<string[]>([]);
  const [addIds, setAddIds] = useState<string[]>([]);
  const [month, setMonth] = useState(dayjs().format("YYYY-MM"));
  const [count, setCount] = useState(10);
  if (!d) return null;
  return (
    <>
      <Typography.Title level={4}>{d.name}</Typography.Title>
      <Typography.Paragraph type="secondary">{PURPOSE[d.purpose]} · 评分标准 {d.rubric_version}{d.note ? ` · ${d.note}` : ""}</Typography.Paragraph>
      <MetricsCards m={d.metrics} />
      <Card size="small" title="样本与校准员" style={{ marginBottom: 16 }}>
        <Space wrap style={{ marginBottom: 12 }}>
          <Select mode="multiple" placeholder="选择已出报告的录像加入" style={{ width: 360 }} value={addIds} onChange={setAddIds}
            options={(recs.data ?? []).map((r) => ({ value: r.id, label: `${r.candidate_name} · ${r.sheet_code}` }))} />
          <Button disabled={!addIds.length} onClick={async () => (await act(() => post(`/calibration/sets/${id}/samples`, { recording_ids: addIds }), "已加入")) && (setAddIds([]), reload())}>加入样本</Button>
          <span>或按月随机抽</span>
          <Input style={{ width: 100 }} value={month} onChange={(e) => setMonth(e.target.value)} placeholder="2026-11" />
          <InputNumber min={1} max={100} value={count} onChange={(v) => setCount(v ?? 10)} addonAfter="条" style={{ width: 120 }} />
          <Button onClick={async () => {
            const r = await act(() => post<{ drawn: number; pool: number }>(`/calibration/sets/${id}/sample-month`, { month, count }));
            if (r) (reload(), Modal.info({ title: `抽到 ${r.drawn} 条（该月可抽 ${r.pool} 条）` }));
          }}>随机抽样</Button>
        </Space>
        <Space wrap style={{ marginBottom: 12 }}>
          <Select mode="multiple" placeholder="选 2–3 位校准员" style={{ width: 360 }} value={cals} onChange={setCals}
            options={(users.data ?? []).filter((u) => u.role === "calibrator" && u.is_active).map((u) => ({ value: u.id, label: u.display_name }))} />
          <Button type="primary" disabled={cals.length < 2 || cals.length > 3} onClick={async () => (await act(() => post(`/calibration/sets/${id}/assign`, { calibrator_ids: cals }), "已分配")) && (setCals([]), reload())}>分配给全部样本</Button>
        </Space>
        <Table<SampleRow> size="small" rowKey="id" dataSource={d.sample_rows} pagination={false} onRow={(r) => ({ onClick: () => setOpen(r.id), style: { cursor: "pointer" } })} columns={[
          { title: "候选人", dataIndex: "candidate_name" },
          { title: "提交时间", dataIndex: "submitted_at", render: (t) => (t ? dayjs(t).format("YYYY-MM-DD") : "—") },
          { title: "状态", dataIndex: "status", render: (s) => <Tag color={SAMPLE_STATUS[s][1]}>{SAMPLE_STATUS[s][0]}</Tag> },
          { title: "校准员", render: (_, r) => r.assignments.map((a) => <Tag key={a.calibrator} color={a.status === "submitted" ? "green" : undefined}>{a.calibrator}{a.status === "submitted" ? " ✓" : ""}</Tag>) },
          { title: "待裁决", dataIndex: "flagged_items", render: (f: string[]) => f.join("、") || "—" },
          { title: "金标准总档位", dataIndex: "gold_total", render: (v) => v ?? "—" },
        ]} />
      </Card>
      <Card size="small" title="条目一致率（监控线：低于 85% 告警，不单独阻止上线）"><ItemRates m={d.metrics} /></Card>
      {open && <SampleDrawer id={open} onClose={() => setOpen(null)} onChanged={reload} />}
    </>
  );
}
