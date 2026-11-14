import { Button, Form, Input, Modal, Select, Switch, Table } from "antd";
import { useState } from "react";
import { patch, post, type S } from "../api/client";
import { ROLE_ZH, useAction, useFetch } from "../components/hooks";
import { IconPlus } from "../components/icons";
import { PageHeader } from "../components/ui";

type U = S<"UserOut">;
const roles = Object.entries(ROLE_ZH).map(([value, label]) => ({ value, label }));

export default function Users() {
  const { data, loading, reload } = useFetch<U[]>("/users");
  const act = useAction();
  const [creating, setCreating] = useState(false);
  const [resetting, setResetting] = useState<U | null>(null);
  const [form] = Form.useForm();
  const [pwForm] = Form.useForm();
  const update = async (u: U, body: object, ok: string) => (await act(() => patch(`/users/${u.id}`, body), ok)) && reload();
  return (
    <>
      <PageHeader
        title="账号管理"
        description="新建的账号和重置过密码的账号，本人首次登录时须先改密码。"
        actions={<Button type="primary" icon={<IconPlus />} onClick={() => setCreating(true)}>新建账号</Button>}
      />
      <Table<U>
        className="table-card"
        scroll={{ x: "max-content" }}
        rowKey="id"
        loading={loading}
        dataSource={data}
        pagination={false}
        columns={[
          { title: "用户名", dataIndex: "username", render: (v) => <span className="mono">{v}</span> },
          { title: "姓名", dataIndex: "display_name", render: (v) => <span className="cell-main">{v}</span> },
          {
            title: "角色",
            dataIndex: "role",
            render: (r, u) => <Select value={r} options={roles} style={{ width: 140 }} onChange={(v) => update(u, { role: v }, "角色已修改")} />,
          },
          { title: "启用", dataIndex: "is_active", render: (a, u) => <Switch checked={a} onChange={(v) => update(u, { is_active: v }, v ? "已启用" : "已停用")} /> },
          { title: "", align: "right", render: (_, u) => <Button size="small" onClick={() => setResetting(u)}>重置密码</Button> },
        ]}
      />
      <Modal
        title="新建账号"
        open={creating}
        onCancel={() => setCreating(false)}
        onOk={async () => {
          const v = await form.validateFields();
          if (await act(() => post("/users", v), "已创建")) {
            setCreating(false);
            form.resetFields();
            reload();
          }
        }}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="username" label="用户名" rules={[{ required: true, pattern: /^[A-Za-z0-9_.-]{3,64}$/, message: "3–64 位字母、数字或 _ . -" }]}>
            <Input />
          </Form.Item>
          <Form.Item name="display_name" label="姓名" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="role" label="角色" rules={[{ required: true }]}>
            <Select options={roles} />
          </Form.Item>
          <Form.Item name="password" label="初始密码" rules={[{ required: true, min: 10, message: "至少 10 位" }]}>
            <Input.Password />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title={`重置密码：${resetting?.username ?? ""}`}
        open={!!resetting}
        onCancel={() => setResetting(null)}
        onOk={async () => {
          const v = await pwForm.validateFields();
          if (resetting && (await act(() => patch(`/users/${resetting.id}`, v), "密码已重置"))) {
            setResetting(null);
            pwForm.resetFields();
          }
        }}
      >
        <Form form={pwForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="password" label="新密码" rules={[{ required: true, min: 10, message: "至少 10 位" }]}>
            <Input.Password />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
