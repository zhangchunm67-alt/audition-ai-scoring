import { Input, Table } from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import type { S } from "../api/client";
import { useFetch } from "../components/hooks";
import { PageHeader, Toolbar } from "../components/ui";

export default function AuditLogs() {
  const [action, setAction] = useState("");
  const [target, setTarget] = useState("");
  const qs = new URLSearchParams({ limit: "500", ...(action ? { action } : {}), ...(target ? { target_id: target } : {}) });
  const { data, loading } = useFetch<S<"AuditOut">[]>(`/audit-logs?${qs}`);
  return (
    <>
      <PageHeader title="审计日志" description="最多显示最近 500 条，可按动作或对象 ID 查找。" />
      <Toolbar>
        <Input.Search placeholder="动作，如 rubric_publish" allowClear onSearch={setAction} style={{ width: 240 }} />
        <Input.Search placeholder="对象 ID" allowClear onSearch={setTarget} style={{ width: 320 }} />
      </Toolbar>
      <Table
        className="table-card"
        scroll={{ x: "max-content" }}
        pagination={{ pageSize: 50, hideOnSinglePage: true, showSizeChanger: false }}
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={data}
        columns={[
          { title: "时间", dataIndex: "at", render: (t) => <span className="cell-time">{dayjs(t).format("YYYY-MM-DD HH:mm:ss")}</span>, width: 170 },
          { title: "操作人", dataIndex: "actor_id", render: (a) => <span className="mono muted">{a?.slice(0, 8) ?? "—"}</span> },
          { title: "动作", dataIndex: "action", render: (a) => <span className="mono cell-main">{a}</span> },
          { title: "对象", render: (_, r) => <span className="nowrap">{r.target_type} <span className="mono muted">{r.target_id.slice(0, 12)}</span></span> },
          { title: "详情", dataIndex: "detail", render: (d) => <span className="mono muted" style={{ display: "inline-block", maxWidth: 520, whiteSpace: "normal", overflowWrap: "anywhere" }}>{JSON.stringify(d)}</span> },
          { title: "IP", dataIndex: "ip", render: (v) => <span className="mono muted">{v}</span> },
        ]}
      />
    </>
  );
}
