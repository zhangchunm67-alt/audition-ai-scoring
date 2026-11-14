import { Alert, Button, Form, Input, Modal } from "antd";
import { post, type S } from "../api/client";
import { useAuth } from "../auth";
import { useAction } from "../components/hooks";

type Vals = { old_password: string; new_password: string; confirm: string };

function PasswordForm({ onDone }: { onDone: () => void }) {
  const { refresh } = useAuth();
  const act = useAction();
  return (
    <Form<Vals> layout="vertical" requiredMark={false} onFinish={async (v) => {
      const r = await act(() => post<S<"MeOut">>("/auth/password", { old_password: v.old_password, new_password: v.new_password }), "密码已修改");
      if (r) { await refresh(); onDone(); }
    }}>
      <Form.Item name="old_password" label="原密码" rules={[{ required: true, message: "请输入原密码" }]}><Input.Password autoComplete="current-password" /></Form.Item>
      <Form.Item name="new_password" label="新密码（至少 10 位）" rules={[{ required: true, min: 10, message: "至少 10 位" }]}><Input.Password autoComplete="new-password" /></Form.Item>
      <Form.Item name="confirm" label="再输一次新密码" dependencies={["new_password"]} rules={[{ required: true, message: "请再输一次" },
        ({ getFieldValue }) => ({ validator: (_, v) => (!v || v === getFieldValue("new_password") ? Promise.resolve() : Promise.reject(new Error("两次输入不一致"))) })]}>
        <Input.Password autoComplete="new-password" />
      </Form.Item>
      <Button type="primary" htmlType="submit">修改密码</Button>
    </Form>
  );
}

/** 管理员设的初始密码或重置的密码：本人先改才能使用系统。 */
export function ForcePasswordChange() {
  const { logout } = useAuth();
  return (
    <div className="auth-card">
      <h2>
        请先修改密码
        <Button type="link" onClick={logout} style={{ paddingInline: 0 }}>退出</Button>
      </h2>
      <Alert type="info" showIcon style={{ marginBottom: 20 }} message="当前密码是管理员设置的，修改后才能使用系统。修改后其他地方的登录会全部失效。" />
      <PasswordForm onDone={() => undefined} />
    </div>
  );
}

export function ChangePasswordModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Modal title="修改密码" open={open} footer={null} onCancel={onClose} destroyOnClose>
      <PasswordForm onDone={onClose} />
    </Modal>
  );
}
