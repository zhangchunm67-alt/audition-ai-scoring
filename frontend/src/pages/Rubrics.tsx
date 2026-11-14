import { Button, Input, Modal, Table } from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { Link } from "react-router-dom";
import { post, type S } from "../api/client";
import { useAuth } from "../auth";
import { useAction, useFetch } from "../components/hooks";
import { IconUpload } from "../components/icons";
import { ConfigStatus, PageHeader, Pill } from "../components/ui";

type Row = S<"RubricSummary">;

export default function Rubrics() {
  const { data, loading, reload } = useFetch<Row[]>("/rubrics");
  const { can } = useAuth();
  const act = useAction();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  return (
    <>
      <PageHeader
        title="评分标准版本"
        description="改评分规则只需导入新版本的计分配置；带“待确认”或“测试占位”标记的版本只能作为草稿使用，不能发布为正式评分标准。"
        actions={can("config.write") && (
          <Button type="primary" icon={<IconUpload />} onClick={() => setOpen(true)}>
            导入 YAML
          </Button>
        )}
      />
      <Table<Row>
        className="table-card"
        rowKey="id"
        loading={loading}
        dataSource={data}
        pagination={false}
        scroll={{ x: "max-content" }}
        columns={[
          { title: "版本", dataIndex: "version", render: (v, r) => <Link className="cell-main mono" to={`/rubrics/${r.id}`}>{v}</Link> },
          { title: "状态", dataIndex: "status", render: (s) => <ConfigStatus status={s} /> },
          { title: "新评分", render: (_, r) => (r.status !== "retired" && r.processing_supported ? <Pill tone="ok" dot={false}>可用</Pill> : <Pill dot={false}>{r.status === "retired" ? "已停用" : "仅供历史追溯"}</Pill>) },
          { title: "发布阻碍", dataIndex: "blocker_count", render: (n: number) => (n ? <Pill tone="bad" dot={false}>{n} 项</Pill> : <span className="faint">无</span>) },
          { title: "配置哈希", dataIndex: "config_hash", render: (h: string) => <span className="mono muted">{h.slice(7, 19)}</span> },
          { title: "导入时间", dataIndex: "created_at", render: (t) => <span className="cell-time">{dayjs(t).format("YYYY-MM-DD HH:mm")}</span> },
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
        <Input.TextArea rows={20} value={text} onChange={(e) => setText(e.target.value)} placeholder="粘贴 config/rubric/*.yaml 的内容" style={{ fontFamily: "var(--font-mono)", fontSize: 12.5, marginTop: 12 }} />
      </Modal>
    </>
  );
}
