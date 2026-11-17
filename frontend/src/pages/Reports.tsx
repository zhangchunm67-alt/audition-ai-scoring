import { Button, DatePicker, Grid, Select, Space, Table, Tag, Tooltip, Typography } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";
import { Link } from "react-router-dom";
import AbilityRadar from "../components/AbilityRadar";
import CandidateIdentity from "../components/CandidateIdentity";
import "./report-ui.css";
import PageHeader from "../components/PageHeader";
import type { S } from "../api/client";
import { LABEL_COLOR, LABEL_TEXT } from "../api/report";
import { useAuth } from "../auth";
import { AUDIENCE_ZH, MODE_ZH, useFetch } from "../components/hooks";

type Row = S<"ReportRow">;
const DIMS: [string, string][] = [["P", "人设塑造"], ["S", "销售循环"], ["L", "表达逻辑"], ["O", "其他"]];

/** 报告与排名（M5-5）：按提交日期范围排名（C32）；新主播只看到本人记录（C31）。 */
export default function Reports() {
  const { can } = useAuth();
  const screens = Grid.useBreakpoint();
  const all = can("report.read_all");
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(all ? [dayjs().subtract(30, "day"), dayjs()] : null);
  const [label, setLabel] = useState<string | undefined>();
  const [sort, setSort] = useState("default");
  const [mode, setMode] = useState("audition");  // 试镜和录播分开排名：取证方式不同，分数不混比
  const qs = new URLSearchParams({
    sort,
    ...(all ? { mode } : {}),
    ...(range ? { date_from: range[0].format("YYYY-MM-DD"), date_to: range[1].format("YYYY-MM-DD") } : {}),
    ...(label ? { label } : {}),
  });
  const { data, loading } = useFetch<Row[]>(`/reports?${qs}`);
  return (
    <>
      <PageHeader title={all ? "报告与排名" : "我的试镜记录"} description={all ? "结合总档位、维度得分与评分证据，复核评估结果。总档位越低越好。" : "查看本人的试镜结果与评分反馈。"} />
      {all && (
        <Space wrap style={{ marginBottom: 16 }}>
          <Select aria-label="录像类型" style={{ width: 100 }} value={mode} onChange={setMode} data-testid="report-mode"
            options={Object.entries(MODE_ZH).map(([value, l]) => ({ value, label: l }))} />
          <DatePicker.RangePicker value={range} onChange={(v) => setRange(v as [Dayjs, Dayjs] | null)} allowClear placeholder={["提交日期从", "到"]} />
          <Select aria-label="结论标签" allowClear placeholder="结论标签" style={{ width: 120 }} value={label} onChange={setLabel}
            options={Object.entries(LABEL_TEXT).map(([value, l]) => ({ value, label: l }))} />
          <Select aria-label="报告排序" style={{ width: 180 }} value={sort} onChange={setSort}
            options={[{ value: "default", label: "综合排序" }, ...DIMS.map(([k, n]) => ({ value: k, label: `按${n}排序` }))]} />
          <Button href={`/api/reports/export.xlsx?${qs}`}>导出 Excel</Button>
        </Space>
      )}
      {all && (
        <Typography.Paragraph type="secondary">
          综合排序：结论标签（推荐 → 待定 → 不推荐）→ 总档位从低到高 → 四个维度分之和从高到低 → 提交时间早的在前。同一日期范围内的报告一起排名，按标签筛选不改变名次。试镜和录播分开排名。
        </Typography.Paragraph>
      )}
      <Table<Row>
        className="reports-reference-table"
        scroll={{ x: 1560 }}
        rowKey="id"
        loading={loading}
        dataSource={data}
        pagination={{ pageSize: 50 }}
        columns={[
          ...(all ? [{ title: "名次", dataIndex: "rank", width: 60 }] : []),
          { title: "候选人", dataIndex: "candidate_name", width: 220, fixed: screens.md ? "left" : undefined, render: (n: string, r: Row) => <CandidateIdentity name={n} phone={r.candidate_phone_masked} videoAssetId={r.candidate_video_asset_id} href={`/reports/${r.id}`} /> },
          { title: "提交时间", dataIndex: "submitted_at", render: (t: string | null) => (t ? dayjs(t).format("YYYY-MM-DD HH:mm") : "—") },
          ...(all ? [] : [{ title: "类型", dataIndex: "mode", render: (m: string) => MODE_ZH[m] ?? m }]),
          { title: "适用达标线", dataIndex: "audience", render: (a: string) => AUDIENCE_ZH[a] ?? a },
          { title: "结论", dataIndex: "label", render: (l: string, r: Row) => <Tooltip title={r.reason}><Tag color={LABEL_COLOR[l]}>{LABEL_TEXT[l]}</Tag></Tooltip> },
          { title: "综合评分 · 总档位", width: 245, render: (_: unknown, r: Row) => <div className="report-table-composite"><div><strong>{r.total_grade}<small> 档</small></strong><span>达标线 &lt; {r.threshold}</span></div><AbilityRadar total={r.total_grade} grades={r.dimension_grades} compact /></div> },
          ...DIMS.map(([k, n]) => ({ title: n, render: (_: unknown, r: Row) => `${r.dimension_scores[k]} 分 · ${r.dimension_grades[k]} 档` })),
          { title: "操作", fixed: screens.md ? "right" : undefined, width: 110, render: (_: unknown, r: Row) => <Link className="report-view-link" to={`/reports/${r.id}`}>查看报告</Link> },
          { title: "标记", render: (_: unknown, r: Row) => (
            <Space size={4} wrap>
              {r.critical && <Tag color="gold">临界</Tag>}
              {r.informal && <Tag>非正式</Tag>}
              {r.low_confidence_count > 0 && <Tag color="orange">低置信 {r.low_confidence_count}</Tag>}
              {r.revision > 1 && <Tag color="blue">第 {r.revision} 版</Tag>}
            </Space>
          ) },
        ]}
      />
    </>
  );
}
