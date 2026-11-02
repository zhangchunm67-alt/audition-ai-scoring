import { Button, Form, Input, Modal, Select, Table, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { post, type S } from "../api/client";
import { useAuth } from "../auth";
import { STATUS_ZH, useAction, useFetch } from "../components/hooks";

type Sheet = S<"SheetOut">;

export default function Sheets() {
  const { data, loading } = useFetch<Sheet[]>("/sheets");
  const products = useFetch<S<"ProductOut">[]>("/products");
  const rubrics = useFetch<S<"RubricSummary">[]>("/rubrics");
  const { can } = useAuth();
  const act = useAction();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();
  return (
    <>
      <Typography.Title level={4}>试镜题单</Typography.Title>
      <Typography.Paragraph type="secondary">
        题单按抽题规则抽好 4 条异议、6 道知识题和朗读稿；候选人按题单在系统外录制，上传录像时选择对应题单。
      </Typography.Paragraph>
      {can("sheet.write") && (
        <Button type="primary" style={{ marginBottom: 16 }} onClick={() => setOpen(true)}>
          生成题单
        </Button>
      )}
      <Table<Sheet>
        rowKey="id"
        loading={loading}
        dataSource={data}
        columns={[
          { title: "题单编号", dataIndex: "code", render: (c, s) => <Link to={`/sheets/${s.id}`}>{c}</Link> },
          { title: "产品", dataIndex: "product_name" },
          { title: "评分标准", dataIndex: "rubric_version", render: (v, s) => (s.uses_draft_config ? <Tag color="orange">{v}（含草稿配置）</Tag> : <Tag color="green">{v}</Tag>) },
          { title: "状态", dataIndex: "status", render: (st) => STATUS_ZH[st] },
          { title: "备注", dataIndex: "note" },
          { title: "生成时间", dataIndex: "created_at", render: (t) => dayjs(t).format("YYYY-MM-DD HH:mm") },
        ]}
      />
      <Modal
        title="生成题单"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={async () => {
          const v = await form.validateFields();
          const s = await act(() => post<Sheet>("/sheets", v), "已生成");
          if (s) nav(`/sheets/${s.id}`);
        }}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="product_id" label="产品" rules={[{ required: true }]}>
            <Select options={(products.data ?? []).map((p) => ({ value: p.id, label: p.name }))} />
          </Form.Item>
          <Form.Item name="rubric_version_id" label="评分标准版本" rules={[{ required: true }]} extra="草稿版本只能用于试用，报告会标注“非正式”。">
            <Select
              options={(rubrics.data ?? [])
                .filter((r) => r.status !== "retired")
                .map((r) => ({ value: r.id, label: `${r.version}（${STATUS_ZH[r.status]}）` }))}
            />
          </Form.Item>
          <Form.Item name="note" label="备注">
            <Input placeholder="如：11 月第 1 批招聘" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
