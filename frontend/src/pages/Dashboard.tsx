import { Alert, Card, DatePicker, Select, Table, Tabs, Tag } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";
import { useFetch } from "../components/hooks";
import { PageHeader, Stat, Toolbar } from "../components/ui";
import { ItemRates, MetricsCards, PURPOSE, pct } from "./Calibration";

type Agreement = { overall: Parameters<typeof MetricsCards>[0]["m"]; sets: { id: string; name: string; purpose: string; final: number; samples: number; dimension_agreement: number | null; conclusion_agreement: number | null }[] };
type Efficiency = {
  submitted: number; done: number; failed: number; in_progress: number; failure_rate: number | null;
  minutes: { median: number | null; p95: number | null; max: number | null }; over_30_min: number; round_retries: number;
  critical_share: number | null; informal_reports: number;
  low_confidence: { item_id: string; name: string; rate: number; count: number; n: number }[];
  daily: { date: string; submitted: number; done: number; failed: number }[];
};

function qs(range: [Dayjs, Dayjs] | null, extra: Record<string, string> = {}) {
  return new URLSearchParams({ ...(range ? { date_from: range[0].format("YYYY-MM-DD"), date_to: range[1].format("YYYY-MM-DD") } : {}), ...extra }).toString();
}

function AgreementTab() {
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null);
  const [setId, setSetId] = useState<string | undefined>();
  const { data } = useFetch<Agreement>(`/dashboard/agreement?${qs(range, setId ? { set_id: setId } : {})}`);
  if (!data) return null;
  return (
    <>
      <Toolbar>
        <Select allowClear placeholder="全部金标准集" style={{ width: 240 }} value={setId} onChange={setSetId} options={data.sets.map((s) => ({ value: s.id, label: s.name }))} />
        <DatePicker.RangePicker value={range} onChange={(v) => setRange(v as [Dayjs, Dayjs] | null)} placeholder={["录像提交日期从", "到"]} />
      </Toolbar>
      <MetricsCards m={data.overall} />
      <div className="split">
        <Card title="按条目"><ItemRates m={data.overall} /></Card>
        <div>
          <Card title="按金标准集">
            <Table size="small" rowKey="id" pagination={false} dataSource={data.sets} scroll={{ x: "max-content" }} columns={[
              { title: "名称", dataIndex: "name" },
              { title: "用途", dataIndex: "purpose", render: (p) => PURPOSE[p] },
              { title: "已定稿", render: (_, r) => `${r.final} / ${r.samples}` },
              { title: "维度一致", dataIndex: "dimension_agreement", render: pct },
              { title: "结论一致", dataIndex: "conclusion_agreement", render: pct },
            ]} />
          </Card>
        </div>
      </div>
    </>
  );
}

function EfficiencyTab() {
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>([dayjs().subtract(30, "day"), dayjs()]);
  const { data: e } = useFetch<Efficiency>(`/dashboard/efficiency?${qs(range)}`);
  if (!e) return null;
  return (
    <>
      <Toolbar>
        <DatePicker.RangePicker value={range} onChange={(v) => setRange(v as [Dayjs, Dayjs] | null)} placeholder={["提交日期从", "到"]} />
      </Toolbar>
      <div className="stat-grid">
        <Stat label="提交" value={e.submitted} unit="条" />
        <Stat label="出报告 / 失败 / 处理中" value={`${e.done} / ${e.failed} / ${e.in_progress}`} />
        <Stat label="失败率" value={pct(e.failure_rate)} />
        <Stat label="处理时长（分钟）中位数 / p95 / 最长" value={`${e.minutes.median ?? "—"} / ${e.minutes.p95 ?? "—"} / ${e.minutes.max ?? "—"}`} />
        <Stat label="超过 30 分钟" value={e.over_30_min} unit="条" tone={e.over_30_min ? "bad" : undefined} />
        <Stat label="临界占比" value={pct(e.critical_share)} note={`整轮重试 ${e.round_retries} 次；非正式报告 ${e.informal_reports} 份`} />
      </div>
      <div className="split">
          <Card title="各条目低置信比例">
            <Table size="small" rowKey="item_id" pagination={false} dataSource={[...e.low_confidence].sort((a, b) => b.rate - a.rate)} columns={[
              { title: "条目", render: (_, r) => r.name },
              { title: "低置信", render: (_, r) => `${r.count} / ${r.n}` },
              { title: "比例", dataIndex: "rate", render: (v: number) => (v > 0.3 ? <Tag color="orange">{pct(v)}</Tag> : pct(v)) },
            ]} />
          </Card>
          <Card title="每日处理量">
            <Table size="small" rowKey="date" pagination={false} dataSource={e.daily} columns={[
              { title: "日期", dataIndex: "date" }, { title: "提交", dataIndex: "submitted" }, { title: "出报告", dataIndex: "done" }, { title: "失败", dataIndex: "failed" },
            ]} />
          </Card>
      </div>
    </>
  );
}

type Ops = {
  backup_ok: { at: string; message?: string } | null; backup_failed: { at: string; message?: string } | null;
  backup_stale: boolean; awaiting_human: number; processing: number;
};

/** 运维状态：备份是否正常（超过 36 小时没有成功备份标红）、等待评委打分的录像数。 */
function OpsBar() {
  const { data } = useFetch<Ops>("/dashboard/ops");
  if (!data) return null;
  const when = (x: { at: string } | null) => (x ? new Date(x.at).toLocaleString("zh-CN") : "从未");
  return (
    <div className="stack-sm" style={{ marginBottom: 16 }}>
      {data.backup_failed && <Alert type="error" showIcon message={`备份失败（${when(data.backup_failed)}）：${data.backup_failed.message ?? ""}`} />}
      <Alert type={data.backup_stale ? "error" : "success"} showIcon
        message={`上次成功备份：${when(data.backup_ok)}${data.backup_stale ? "（超过 36 小时，请检查 NAS 和每日任务）" : ""}`} />
      {data.awaiting_human > 0 && <Alert type="warning" showIcon message={`有 ${data.awaiting_human} 条录像等待评委打分`} />}
    </div>
  );
}

export default function Dashboard() {
  return (
    <>
      <PageHeader title="看板" description="AI 与金标准的一致率，以及录像处理的效率和运行状态。" />
      <OpsBar />
      <Tabs items={[{ key: "a", label: "一致率", children: <AgreementTab /> }, { key: "e", label: "效率", children: <EfficiencyTab /> }]} />
    </>
  );
}
