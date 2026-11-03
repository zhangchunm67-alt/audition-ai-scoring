import { Button, Select, Space, Table, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { S } from "../api/client";
import { useAuth } from "../auth";
import { AUDIENCE_ZH, useFetch } from "../components/hooks";

export const REC_STATUS: Record<string, [string, string]> = {
  uploading: ["上传中", "processing"],
  uploaded: ["待标分段", "orange"],
  submitted: ["已提交，待处理", "blue"],
  processing: ["处理中", "blue"],
  done: ["已出报告", "green"],
  failed: ["处理失败", "red"],
  cancelled: ["已取消", "default"],
};

export default function Recordings() {
  const [status, setStatus] = useState<string | undefined>();
  const { data, loading } = useFetch<S<"RecordingOut">[]>(`/recordings${status ? `?status=${status}` : ""}`);
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
          { title: "题单", dataIndex: "sheet_code" },
          { title: "产品", dataIndex: "product_name" },
          { title: "适用达标线", dataIndex: "audience", render: (a) => AUDIENCE_ZH[a] ?? a },
          { title: "道具", dataIndex: "props_available", render: (p) => (p ? "有" : "无") },
          { title: "状态", dataIndex: "status", render: (s) => <Tag color={REC_STATUS[s]?.[1]}>{REC_STATUS[s]?.[0] ?? s}</Tag> },
          { title: "登记时间", dataIndex: "created_at", render: (t) => dayjs(t).format("YYYY-MM-DD HH:mm") },
        ]}
      />
    </>
  );
}
