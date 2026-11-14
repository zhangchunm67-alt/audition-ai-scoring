import { Button, Table } from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { S } from "../api/client";
import { useAuth } from "../auth";
import { AUDIENCE_ZH, MODE_ZH, useFetch } from "../components/hooks";
import { IconPlus } from "../components/icons";
import { FilterPills, PageHeader, Pill, Toolbar, type Tone } from "../components/ui";

/** 录像状态：[显示名, 色调]。黄色＝等人处理，蓝色＝系统在处理。 */
export const REC_STATUS: Record<string, [string, Tone]> = {
  uploading: ["上传中", "progress"],
  uploaded: ["待标注", "warn"],
  submitted: ["已提交，待处理", "info"],
  processing: ["处理中", "progress"],
  awaiting_human: ["等待评委打分", "warn"],
  done: ["已出报告", "ok"],
  failed: ["处理失败", "bad"],
  cancelled: ["已取消", "neutral"],
};

export function RecStatus({ status, large }: { status: string; large?: boolean }) {
  const [label, tone] = REC_STATUS[status] ?? [status, "neutral" as Tone];
  return <Pill tone={tone} large={large}>{label}</Pill>;
}

type Rec = S<"RecordingOut">;

export default function Recordings() {
  const [status, setStatus] = useState("all");
  const { data, loading } = useFetch<Rec[]>("/recordings");
  const { can } = useAuth();
  const nav = useNavigate();
  const all = data ?? [];
  const count = (s: string) => all.filter((r) => r.status === s).length;
  // 只列出有录像的状态，避免一排全是 0；当前选中的状态始终保留。
  const options = [
    { value: "all", label: "全部", count: all.length },
    ...Object.entries(REC_STATUS)
      .map(([value, [label]]) => ({ value, label, count: count(value) }))
      .filter((o) => o.count > 0 || o.value === status),
  ];
  const rows = status === "all" ? all : all.filter((r) => r.status === status);
  return (
    <>
      <PageHeader
        title="试镜录像"
        description="每条录像从上传、标注到出报告的进度。黄色状态等人处理，蓝色状态系统正在处理。"
        actions={can("recording.upload") && (
          <Button type="primary" icon={<IconPlus />} onClick={() => nav("/recordings/new")}>
            上传录像
          </Button>
        )}
      />
      <Toolbar>
        <FilterPills label="按状态筛选" value={status} onChange={setStatus} options={options} />
      </Toolbar>
      <Table<Rec>
        className="table-card"
        rowKey="id"
        loading={loading}
        dataSource={rows}
        scroll={{ x: "max-content" }}
        pagination={{ pageSize: 20, hideOnSinglePage: true, showSizeChanger: false }}
        locale={{ emptyText: status === "all" ? "还没有录像。点右上角“上传录像”开始。" : "这个状态下没有录像" }}
        columns={[
          {
            title: "候选人", dataIndex: "candidate_name", render: (n, r) => (
              <>
                <Link className="cell-main" to={`/recordings/${r.id}`}>{n}</Link>
                <span className="cell-sub mono">{r.sheet_code}</span>
              </>
            ),
          },
          { title: "类型", dataIndex: "mode", render: (m) => MODE_ZH[m] ?? m },
          { title: "产品", dataIndex: "product_name" },
          { title: "适用达标线", dataIndex: "audience", render: (a) => AUDIENCE_ZH[a] ?? a },
          { title: "道具", dataIndex: "props_available", render: (p) => (p ? "有" : <span className="faint">无</span>) },
          { title: "状态", dataIndex: "status", render: (s) => <RecStatus status={s} /> },
          { title: "登记时间", dataIndex: "created_at", render: (t) => <span className="cell-time">{dayjs(t).format("YYYY-MM-DD HH:mm")}</span> },
          {
            title: "", key: "go", align: "right", render: (_, r) => (r.status === "done" && r.report_id
              ? <Link to={`/reports/${r.report_id}`}>看报告</Link>
              : <Link to={`/recordings/${r.id}`} className="muted">打开</Link>),
          },
        ]}
      />
    </>
  );
}
