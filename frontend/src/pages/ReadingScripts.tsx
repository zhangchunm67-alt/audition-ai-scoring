import { Button, Form, Input, Modal, Switch, Table } from "antd";
import { useState } from "react";
import { post, put, type S } from "../api/client";
import { useAuth } from "../auth";
import { useAction, useFetch } from "../components/hooks";
import { IconPlus } from "../components/icons";
import { PageHeader, Pill } from "../components/ui";

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
      <PageHeader
        title="朗读稿"
        description="约 250 字的标准文稿，建议 ≥ 3 篇轮换；“人设塑造·普通话标准”以此为参考文本。"
        actions={can("config.write") && (
          <Button type="primary" icon={<IconPlus />} onClick={() => open()}>
            新增朗读稿
          </Button>
        )}
      />
      <Table<R>
        className="table-card"
        pagination={{ pageSize: 20, hideOnSinglePage: true, showSizeChanger: false }}
        locale={{ emptyText: "还没有朗读稿" }}
        rowKey="id"
        loading={loading}
        dataSource={data}
        columns={[
          { title: "标题", dataIndex: "title", render: (t) => <span className="cell-main">{t}</span> },
          { title: "字数", dataIndex: "char_count", render: (n) => <span className="num">{n}</span> },
          { title: "启用", dataIndex: "active", render: (a) => (a ? <Pill tone="ok">启用</Pill> : <Pill>停用</Pill>) },
          ...(can("config.write") ? [{ title: "", align: "right" as const, render: (_: unknown, r: R) => <Button size="small" onClick={() => open(r)}>编辑</Button> }] : []),
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
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
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
