import { Button, Select, Space, Table, Tag, Typography } from "antd";
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

export default function Recordings() {
  const [status, setStatus] = useState<string | undefined>();
  const { data, loading, reload } = useFetch<S<"RecordingOut">[]>(`/recordings${status ? `?status=${status}` : ""}`);
  const processing = data?.some(r => ["submitted", "processing"].includes(r.status));
  useEffect(() => {
    if (!processing) return;
    const timer = setInterval(reload, 5000);
    return () => clearInterval(timer);
  }, [processing, reload]);
  const { can } = useAuth();
  const nav = useNavigate();
  return (
    <>
      <Typography.Title level={4}>试镜录像</Typography.Title>
      <Space style={{ marginBottom: 16 }}>
        {can("recording.upload") && (
          <Button type="primary" onClick={() => nav("/recordings/new")}>
            上传录像
          </Button>
        )}
        <Select allowClear placeholder="按状态筛选" style={{ width: 180 }} value={status} onChange={setStatus}
          options={Object.entries(REC_STATUS).map(([value, [label]]) => ({ value, label }))} />
      </Space>
      <Table
        rowKey="id"
        loading={loading}
        dataSource={data}
        columns={[
          { title: "候选人", dataIndex: "candidate_name", render: (n, r) => <Link to={`/recordings/${r.id}`}>{n}</Link> },
          { title: "类型", dataIndex: "mode", render: (m) => MODE_ZH[m] ?? m },
          { title: "题单 / 录播编号", dataIndex: "sheet_code" },
          { title: "产品", dataIndex: "product_name" },
          { title: "适用达标线", dataIndex: "audience", render: (a) => AUDIENCE_ZH[a] ?? a },
          { title: "道具", dataIndex: "props_available", render: (p) => (p ? "有" : "无") },
          { title: "状态", dataIndex: "status", width: 160, render: (s, r) => <div><Tag color={REC_STATUS[s]?.[1]}>{REC_STATUS[s]?.[0] ?? s}</Tag>{["submitted", "processing"].includes(s) && r.scoring_runs?.map(run => <Typography.Text key={run.round_no} type="secondary" style={{ display: "block", fontSize: 12 }}>第 {run.round_no} 轮 · {run.status === "queued" ? "排队中" : run.status === "completed" ? "已完成" : run.status === "failed" ? "重试处理中" : run.stage === "asr" ? "语音转写" : run.stage === "detectors" ? `${run.detectors_completed + run.detectors_failed}/${run.detectors_total ?? "—"} 项已返回` : "处理中"}</Typography.Text>)}</div> },
          { title: "操作", key: "action", render: (_, r) => ["submitted", "processing"].includes(r.status) ? <Link to={`/recordings/${r.id}`}>查看进度</Link> : null },
          { title: "登记时间", dataIndex: "created_at", render: (t) => dayjs(t).format("YYYY-MM-DD HH:mm") },
        ]}
      />
    </>
  );
}
