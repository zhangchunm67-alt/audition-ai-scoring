import { Input, Space, Table, Typography } from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import type { S } from "../api/client";
import { useFetch } from "../components/hooks";

export default function AuditLogs() {
  const [action, setAction] = useState("");
  const [target, setTarget] = useState("");
  const qs = new URLSearchParams({ limit: "500", ...(action ? { action } : {}), ...(target ? { target_id: target } : {}) });
  const { data, loading } = useFetch<S<"AuditOut">[]>(`/audit-logs?${qs}`);
  return (
    <>
      <Typography.Title level={4}>审计日志</Typography.Title>
      <Space style={{ marginBottom: 16 }}>
        <Input.Search placeholder="动作，如 rubric_publish" allowClear onSearch={setAction} style={{ width: 240 }} />
        <Input.Search placeholder="对象 ID" allowClear onSearch={setTarget} style={{ width: 320 }} />
      </Space>
      <Table
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={data}
        columns={[
          { title: "时间", dataIndex: "at", render: (t) => dayjs(t).format("YYYY-MM-DD HH:mm:ss"), width: 170 },
          { title: "操作人", dataIndex: "actor_id", render: (a) => <Typography.Text code>{a?.slice(0, 8) ?? "—"}</Typography.Text> },
          { title: "动作", dataIndex: "action" },
          { title: "对象", render: (_, r) => `${r.target_type} ${r.target_id.slice(0, 12)}` },
          { title: "详情", dataIndex: "detail", render: (d) => <Typography.Text type="secondary">{JSON.stringify(d)}</Typography.Text> },
          { title: "IP", dataIndex: "ip" },
        ]}
      />
    </>
  );
}
