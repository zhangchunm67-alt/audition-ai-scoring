import { Button, Input, Modal, Space, Table, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { Link } from "react-router-dom";
import { post, type S } from "../api/client";
import { useAuth } from "../auth";
import { STATUS_ZH, useAction, useFetch } from "../components/hooks";

type Row = S<"RubricSummary">;

export default function Rubrics() {
  const { data, loading, reload } = useFetch<Row[]>("/rubrics");
  const { can } = useAuth();
  const act = useAction();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  return (
    <>
      <Space style={{ marginBottom: 16, justifyContent: "space-between", width: "100%" }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          评分标准版本
        </Typography.Title>
        {can("config.write") && (
          <Button type="primary" onClick={() => setOpen(true)}>
            导入 YAML
          </Button>
        )}
      </Space>
      <Typography.Paragraph type="secondary">
        改评分规则只需导入新版本的计分配置；带“待确认”或“测试占位”标记的版本只能作为草稿使用，不能发布为正式评分标准。
      </Typography.Paragraph>
      <Table<Row>
        rowKey="id"
        loading={loading}
        dataSource={data}
        pagination={false}
        columns={[
          { title: "版本", dataIndex: "version", render: (v, r) => <Link to={`/rubrics/${r.id}`}>{v}</Link> },
          { title: "状态", dataIndex: "status", render: (s) => <Tag color={s === "published" ? "green" : s === "draft" ? "orange" : "default"}>{STATUS_ZH[s]}</Tag> },
          { title: "发布阻碍", dataIndex: "blocker_count", render: (n: number) => (n ? <Tag color="red">{n} 项</Tag> : <Tag color="green">无</Tag>) },
          { title: "配置哈希", dataIndex: "config_hash", render: (h: string) => <Typography.Text code>{h.slice(7, 19)}</Typography.Text> },
          { title: "导入时间", dataIndex: "created_at", render: (t) => dayjs(t).format("YYYY-MM-DD HH:mm") },
        ]}
      />
      <Modal
        title="导入计分配置（YAML）"
        open={open}
        width={800}
        okText="导入"
        onCancel={() => setOpen(false)}
        onOk={async () => {
          const r = await act(() => post("/rubrics", { yaml_text: text }), "已导入为草稿");
          if (r) {
            setOpen(false);
            setText("");
            reload();
          }
        }}
      >
        <Input.TextArea rows={20} value={text} onChange={(e) => setText(e.target.value)} placeholder="粘贴 config/rubric/*.yaml 的内容" style={{ fontFamily: "monospace" }} />
      </Modal>
    </>
  );
}
