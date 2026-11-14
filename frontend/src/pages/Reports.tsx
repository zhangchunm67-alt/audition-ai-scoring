import { Button, DatePicker, Select, Space, Table, Tag, Tooltip } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";
import { Link } from "react-router-dom";
import type { S } from "../api/client";
import { LABEL_TEXT, LABEL_TONE } from "../api/report";
import { useAuth } from "../auth";
import { AUDIENCE_ZH, MODE_ZH, useFetch } from "../components/hooks";
import { IconDownload } from "../components/icons";
import { MiniScore, PageHeader, Pill, Toolbar } from "../components/ui";

type Row = S<"ReportRow">;
const DIMS: [string, string][] = [["P", "人设塑造"], ["S", "销售循环"], ["L", "表达逻辑"], ["O", "其他"]];

/** 报告与排名（M5-5）：按提交日期范围排名（C32）；新主播只看到本人记录（C31）。 */
export default function Reports() {
  const { can } = useAuth();
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
      <PageHeader
        title={all ? "报告与排名" : "我的试镜记录"}
        description={all
          ? "同一日期范围内的报告一起排名，试镜和录播分开排。综合排序依次看：结论（推荐 → 待定 → 不推荐）、总档位从低到高、四个维度分之和从高到低、提交时间早的在前。按结论筛选不改变名次。"
          : "你参加过的试镜和对应的评分报告。"}
        actions={all && <Button icon={<IconDownload />} href={`/api/reports/export.xlsx?${qs}`}>导出 Excel</Button>}
      />
      {all && (
        <Toolbar>
          <Select style={{ width: 96 }} value={mode} onChange={setMode} data-testid="report-mode"
            options={Object.entries(MODE_ZH).map(([value, l]) => ({ value, label: l }))} />
          <DatePicker.RangePicker value={range} onChange={(v) => setRange(v as [Dayjs, Dayjs] | null)} allowClear placeholder={["提交日期从", "到"]} />
          <Select allowClear placeholder="全部结论" style={{ width: 120 }} value={label} onChange={setLabel}
            options={Object.entries(LABEL_TEXT).map(([value, l]) => ({ value, label: l }))} />
          <Select style={{ width: 168 }} value={sort} onChange={setSort}
            options={[{ value: "default", label: "综合排序" }, ...DIMS.map(([k, n]) => ({ value: k, label: `按${n}排序` }))]} />
        </Toolbar>
      )}
      <Table<Row>
        className="table-card"
        rowKey="id"
        loading={loading}
        dataSource={data}
        scroll={{ x: "max-content" }}
        pagination={{ pageSize: 50, hideOnSinglePage: true, showSizeChanger: false }}
        locale={{ emptyText: all ? "这个范围内没有报告，换个日期或类型试试" : "还没有试镜记录" }}
        columns={[
          ...(all ? [{ title: "名次", dataIndex: "rank", width: 64, render: (n: number) => <span className={`rank${n <= 3 ? " rank-top" : ""}`}>{n}</span> }] : []),
          {
            title: "候选人", dataIndex: "candidate_name", render: (n: string, r: Row) => (
              <>
                <Link className="cell-main" to={`/reports/${r.id}`}>{n}</Link>
                <span className="cell-sub">{AUDIENCE_ZH[r.audience] ?? r.audience}{all ? "" : ` · ${MODE_ZH[r.mode] ?? r.mode}`}</span>
              </>
            ),
          },
          { title: "结论", dataIndex: "label", render: (l: string, r: Row) => <Tooltip title={r.reason}><span><Pill tone={LABEL_TONE[l]}>{LABEL_TEXT[l]}</Pill></span></Tooltip> },
          {
            title: "总档位", render: (_: unknown, r: Row) => (
              <span className="num nowrap"><b style={{ fontWeight: 600 }}>{r.total_grade}</b> <span className="faint">/ 达标线 &lt; {r.threshold}</span></span>
            ),
          },
          ...DIMS.map(([k, n]) => ({
            title: n, render: (_: unknown, r: Row) => (
              <MiniScore ratio={r.dimension_scores[k] == null ? null : r.dimension_scores[k] / 100}
                text={<>{r.dimension_scores[k]} 分 <span className="faint">· {r.dimension_grades[k]} 档</span></>} />
            ),
          })),
          { title: "标记", render: (_: unknown, r: Row) => (
            <Space size={4} wrap>
              {r.critical && <Tag color="gold">临界</Tag>}
              {r.informal && <Tag>非正式</Tag>}
              {r.low_confidence_count > 0 && <Tag color="orange">低置信 {r.low_confidence_count}</Tag>}
              {r.revision > 1 && <Tag color="blue">第 {r.revision} 版</Tag>}
            </Space>
          ) },
          { title: "提交时间", dataIndex: "submitted_at", render: (t: string | null) => <span className="cell-time">{t ? dayjs(t).format("YYYY-MM-DD HH:mm") : "—"}</span> },
        ]}
      />
    </>
  );
}
