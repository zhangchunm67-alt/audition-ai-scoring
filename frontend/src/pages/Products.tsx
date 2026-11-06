import { Button, Form, Input, Modal, Table, Tag, Typography } from "antd";
import { useState } from "react";
import { Link } from "react-router-dom";
import { post, type S } from "../api/client";
import { useAuth } from "../auth";
import { useAction, useFetch } from "../components/hooks";

type P = S<"ProductOut">;

export default function Products() {
  const { data, loading, reload } = useFetch<P[]>("/products");
  const { can } = useAuth();
  const act = useAction();
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();
  return (
    <>
      <Typography.Title level={4}>产品与题库</Typography.Title>
      {can("config.write") && (
        <Button type="primary" style={{ marginBottom: 16 }} onClick={() => setOpen(true)}>
          新建产品
        </Button>
      )}
      <Table<P>
        rowKey="id"
        loading={loading}
        dataSource={data}
        pagination={false}
        columns={[
          { title: "产品", dataIndex: "name", render: (n, p) => <Link to={`/products/${p.id}`}>{n}</Link> },
          { title: "编码", dataIndex: "code" },
          { title: "已发布卖点卡", dataIndex: "published_card_version", render: (v) => (v ? <Tag color="green">第 {v} 版</Tag> : <Tag color="red">无</Tag>) },
          { title: "可用异议", dataIndex: "active_objections", render: (n: number) => <Tag color={n >= 20 ? "green" : "orange"}>{n} 条</Tag> },
          { title: "可用知识题", dataIndex: "active_questions", render: (n: number) => <Tag color={n >= 30 ? "green" : "default"}>{n} 道</Tag> },
        ]}
      />
      <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
        PRD 建议规模：异议库 ≥ 20 条（每次抽 4 条）。评分表 20261105 已删除保险知识，新版评分标准不再抽知识题。
      </Typography.Paragraph>
      <Modal
        title="新建产品"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={async () => {
          const v = await form.validateFields();
          if (await act(() => post("/products", v), "已创建")) {
            setOpen(false);
            form.resetFields();
            reload();
          }
        }}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="产品名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="code" label="编码" rules={[{ required: true, pattern: /^[A-Za-z0-9_-]{2,64}$/, message: "2–64 位字母、数字、_ 或 -" }]}>
            <Input />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
