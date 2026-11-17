import { Button, Input, Select, Space, Table, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { S } from "../api/client";
import { useAuth } from "../auth";
import { AUDIENCE_ZH, MODE_ZH, useFetch } from "../components/hooks";

export const REC_STATUS: Record<string, [string, string]> = {
  uploading: ["上传中", "processing"],
  uploaded: ["待标注", "orange"],
  submitted: ["已提交，待处理", "blue"],
  processing: ["处理中", "blue"],
  awaiting_human: ["等待评委打分", "gold"],
  done: ["已出报告", "green"],
  failed: ["处理失败", "red"],
  cancelled: ["已取消", "default"],
};

type Recording = S<"RecordingOut">;
type Queue = "all" | "action" | "processing" | "done";

export default function Recordings() {
  const [status, setStatus] = useState<string | undefined>();
  const [queue, setQueue] = useState<Queue>("all");
  const [search, setSearch] = useState("");
  const { data, loading, error, reload } = useFetch<Recording[]>("/recordings");
  const processing = data?.some(r => ["submitted", "processing"].includes(r.status));
  useEffect(() => {
    if (!processing) return;
    const timer = setInterval(reload, 5000);
    return () => clearInterval(timer);
  }, [processing, reload]);
  const { can } = useAuth();
  const nav = useNavigate();
  const actionable = (r: Recording) => (can("recording.upload") && ["uploading", "uploaded", "failed"].includes(r.status)) || (can("human.score") && r.status === "awaiting_human");
  const queues: { key: Queue; label: string; match: (r: Recording) => boolean }[] = [
    { key: "all", label: "全部录像", match: () => true },
    { key: "action", label: "待我处理", match: actionable },
    { key: "processing", label: "处理中", match: (r) => ["submitted", "processing"].includes(r.status) },
    { key: "done", label: "已出报告", match: (r) => r.status === "done" },
  ];
  const filtered = (data ?? []).filter((r) => queues.find((q) => q.key === queue)!.match(r)
    && (!status || r.status === status)
    && (!search.trim() || [r.candidate_name, r.product_name, r.sheet_code].some((v) => v?.toLowerCase().includes(search.trim().toLowerCase()))));
  const action = (r: Recording) => {
    if (r.status === "done" && r.report_id) return { text: "查看报告", path: `/reports/${r.report_id}` };
    const text = actionable(r) ? ({ uploaded: "继续标注", uploading: "继续上传", failed: "查看失败原因", awaiting_human: "去打分" }[r.status] ?? "查看录像") : ["submitted", "processing"].includes(r.status) ? "查看进度" : "查看录像";
    return { text, path: `/recordings/${r.id}` };
  };
  return (
    <>
      <div className="list-heading">
        <Typography.Title level={1}>试镜录像</Typography.Title>
        {can("recording.upload") && <Button type="primary" onClick={() => nav("/recordings/new")}>上传录像</Button>}
      </div>
      <div className="task-queues" role="group" aria-label="录像任务">
        {queues.map((q) => <button key={q.key} type="button" aria-pressed={queue === q.key} onClick={() => { setQueue(q.key); setStatus(undefined); }}>
          {q.label}<span>{data ? data.filter(q.match).length : "—"}</span>
        </button>)}
      </div>
      <div className="table-toolbar">
        <Input.Search aria-label="搜索录像" placeholder="候选人、产品或编号" allowClear value={search} onChange={(e) => setSearch(e.target.value)} style={{ width: 260 }} />
        <Select aria-label="按状态筛选" allowClear placeholder="全部状态" style={{ width: 180 }} value={status} onChange={setStatus}
          options={Object.entries(REC_STATUS).map(([value, [label]]) => ({ value, label }))} />
        <Button onClick={reload} loading={loading}>刷新</Button>
        <Typography.Text type="secondary" className="result-count">{error ? "加载失败，请刷新重试" : loading ? "加载中…" : `共 ${filtered.length} 条`}</Typography.Text>
      </div>
      <Table<Recording>
        size="small"
        scroll={{ x: 860 }}
        rowKey="id"
        loading={loading}
        dataSource={filtered}
        expandable={{ expandedRowRender: (r) => <Space wrap size={[24, 8]}>
          <span>编号：{r.sheet_code}</span><span>达标线：{AUDIENCE_ZH[r.audience] ?? r.audience}</span><span>道具：{r.props_available ? "有" : "无"}</span>
        </Space> }}
        columns={[
          { title: "候选人", dataIndex: "candidate_name", width: 120, render: (n, r) => <Link to={`/recordings/${r.id}`}>{n}</Link> },
          { title: "产品", dataIndex: "product_name", width: 200 },
          { title: "类型", dataIndex: "mode", width: 70, render: (m) => MODE_ZH[m] ?? m },
          { title: "状态", dataIndex: "status", width: 160, render: (s, r) => <div><Tag color={REC_STATUS[s]?.[1]}>{REC_STATUS[s]?.[0] ?? s}</Tag>{["submitted", "processing"].includes(s) && r.scoring_runs?.map(run => <Typography.Text key={run.round_no} type="secondary" style={{ display: "block", fontSize: 12 }}>第 {run.round_no} 轮 · {run.status === "queued" ? "排队中" : run.status === "completed" ? "已完成" : run.status === "failed" ? "重试处理中" : run.stage === "asr" ? "语音转写" : run.stage === "detectors" ? `${run.detectors_completed + run.detectors_failed}/${run.detectors_total ?? "—"} 项已返回` : "处理中"}</Typography.Text>)}</div> },
          { title: "登记时间", dataIndex: "created_at", width: 160, render: (t) => dayjs(t).format("MM-DD HH:mm") },
          { title: "操作", key: "action", width: 120, fixed: "right", render: (_, r) => <Link to={action(r).path}>{action(r).text}</Link> },
        ]}
      />
    </>
  );
}
