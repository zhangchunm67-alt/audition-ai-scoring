import { Alert, Button, Card, Form, Input } from "antd";
import { useState } from "react";
import { useAuth } from "../auth";

export default function Login() {
  const { login } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <div style={{ display: "flex", justifyContent: "center", paddingTop: 120 }}>
      <Card title="试镜评分后台 · 登录" style={{ width: 360 }}>
        {error && <Alert type="error" message={error} style={{ marginBottom: 16 }} />}
        <Form
          layout="vertical"
          onFinish={async (v: { username: string; password: string }) => {
            setBusy(true);
            try {
              await login(v.username, v.password);
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <Form.Item name="username" label="用户名" rules={[{ required: true }]}>
            <Input autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true }]}>
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={busy}>
            登录
          </Button>
        </Form>
      </Card>
    </div>
  );
}
