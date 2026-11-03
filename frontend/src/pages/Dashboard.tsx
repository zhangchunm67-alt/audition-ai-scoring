import { Card, Col, DatePicker, Row, Select, Space, Statistic, Table, Tabs, Tag, Typography } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";
import { useFetch } from "../components/hooks";
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
      <Space style={{ marginBottom: 16 }}>
        <Select allowClear placeholder="全部金标准集" style={{ width: 240 }} value={setId} onChange={setSetId} options={data.sets.map((s) => ({ value: s.id, label: s.name }))} />
        <DatePicker.RangePicker value={range} onChange={(v) => setRange(v as [Dayjs, Dayjs] | null)} placeholder={["录像提交日期从", "到"]} />
      </Space>
      <MetricsCards m={data.overall} />
      <Row gutter={16}>
        <Col span={12}><Card size="small" title="按条目"><ItemRates m={data.overall} /></Card></Col>
        <Col span={12}>
          <Card size="small" title="按金标准集">
            <Table size="small" rowKey="id" pagination={false} dataSource={data.sets} columns={[
              { title: "名称", dataIndex: "name" },
              { title: "用途", dataIndex: "purpose", render: (p) => PURPOSE[p] },
              { title: "已定稿", render: (_, r) => `${r.final} / ${r.samples}` },
              { title: "维度一致", dataIndex: "dimension_agreement", render: pct },
              { title: "结论一致", dataIndex: "conclusion_agreement", render: pct },
            ]} />
          </Card>
        </Col>
      </Row>
    </>
  );
}

function EfficiencyTab() {
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>([dayjs().subtract(30, "day"), dayjs()]);
  const { data: e } = useFetch<Efficiency>(`/dashboard/efficiency?${qs(range)}`);
  if (!e) return null;
  return (
    <>
      <DatePicker.RangePicker style={{ marginBottom: 16 }} value={range} onChange={(v) => setRange(v as [Dayjs, Dayjs] | null)} placeholder={["提交日期从", "到"]} />
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={4}><Statistic title="提交" value={e.submitted} /></Col>
        <Col span={4}><Statistic title="出报告 / 失败 / 处理中" value={`${e.done} / ${e.failed} / ${e.in_progress}`} /></Col>
        <Col span={4}><Statistic title="失败率" value={pct(e.failure_rate)} /></Col>
        <Col span={6}><Statistic title="处理时长（分钟）中位数 / p95 / 最长" value={`${e.minutes.median ?? "—"} / ${e.minutes.p95 ?? "—"} / ${e.minutes.max ?? "—"}`} /></Col>
        <Col span={3}><Statistic title="超过 30 分钟" value={e.over_30_min} valueStyle={{ color: e.over_30_min ? "#cf1322" : undefined }} /></Col>
        <Col span={3}><Statistic title="临界占比" value={pct(e.critical_share)} /></Col>
      </Row>
      <Typography.Paragraph type="secondary">整轮重试 {e.round_retries} 次；非正式报告 {e.informal_reports} 份。</Typography.Paragraph>
      <Row gutter={16}>
        <Col span={12}>
          <Card size="small" title="各条目低置信比例">
            <Table size="small" rowKey="item_id" pagination={false} dataSource={[...e.low_confidence].sort((a, b) => b.rate - a.rate)} columns={[
              { title: "条目", render: (_, r) => `${r.item_id} ${r.name}` },
              { title: "低置信", render: (_, r) => `${r.count} / ${r.n}` },
              { title: "比例", dataIndex: "rate", render: (v: number) => (v > 0.3 ? <Tag color="orange">{pct(v)}</Tag> : pct(v)) },
            ]} />
          </Card>
        </Col>
        <Col span={12}>
          <Card size="small" title="每日处理量">
            <Table size="small" rowKey="date" pagination={false} dataSource={e.daily} columns={[
              { title: "日期", dataIndex: "date" }, { title: "提交", dataIndex: "submitted" }, { title: "出报告", dataIndex: "done" }, { title: "失败", dataIndex: "failed" },
            ]} />
          </Card>
        </Col>
      </Row>
    </>
  );
}

export default function Dashboard() {
  return (
    <>
      <Typography.Title level={4}>看板</Typography.Title>
      <Tabs items={[{ key: "a", label: "一致率", children: <AgreementTab /> }, { key: "e", label: "效率", children: <EfficiencyTab /> }]} />
    </>
  );
}
