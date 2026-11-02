import { Button, Form, Input, Modal, Switch, Table, Tag, Typography } from "antd";
import { useState } from "react";
import { post, put, type S } from "../api/client";
import { useAuth } from "../auth";
import { useAction, useFetch } from "../components/hooks";

type R = S<"ScriptOut">;

export default function ReadingScripts() {
  const { data, loading, reload } = useFetch<R[]>("/reading-scripts");
  const { can } = useAuth();
  const act = useAction();
  const [edit, setEdit] = useState<Partial<R> | null>(null);
  const [form] = Form.useForm();
  const open = (r?: R) => {
    form.setFieldsValue(r ?? { active: true, title: "", text: "" });
    setEdit(r ?? {});
  };
  return (
    <>
      <Typography.Title level={4}>朗读稿</Typography.Title>
      <Typography.Paragraph type="secondary">约 250 字的标准文稿，建议 ≥ 3 篇轮换；P3 普通话评测以此为参考文本。</Typography.Paragraph>
      {can("config.write") && (
        <Button type="primary" style={{ marginBottom: 16 }} onClick={() => open()}>
          新增朗读稿
        </Button>
      )}
      <Table<R>
        rowKey="id"
        loading={loading}
        dataSource={data}
        columns={[
          { title: "标题", dataIndex: "title" },
          { title: "字数", dataIndex: "char_count" },
          { title: "启用", dataIndex: "active", render: (a) => (a ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>) },
          ...(can("config.write") ? [{ title: "", render: (_: unknown, r: R) => <Button size="small" onClick={() => open(r)}>编辑</Button> }] : []),
        ]}
      />
      <Modal
        title="朗读稿"
        open={!!edit}
        width={720}
        onCancel={() => setEdit(null)}
        onOk={async () => {
          const v = await form.validateFields();
          const ok = await act(() => (edit?.id ? put(`/reading-scripts/${edit.id}`, v) : post("/reading-scripts", v)), "已保存");
          if (ok) {
            setEdit(null);
            reload();
          }
        }}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="title" label="标题" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="text" label="正文" rules={[{ required: true }]}>
            <Input.TextArea rows={10} showCount />
          </Form.Item>
          <Form.Item name="active" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
