import { Alert, Button, Form, Input } from "antd";
import { useState } from "react";
import { useAuth } from "../auth";
import { BRAND, BrandMark } from "../components/ui";

export default function Login() {
  const { login } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <div className="auth">
      <aside className="auth-aside">
        <div className="brand">
          <BrandMark />
          <span>
            <div className="brand-name">{BRAND.name}</div>
            <div className="brand-sub">{BRAND.sub}</div>
          </span>
        </div>
        <div className="auth-lede">
          <h1>每一分都有出处，<br />每个结论都能回看。</h1>
          <p>上传试镜或直播录播，系统按评分表逐条给分，并把依据定位到视频里的那一句。评委确认、校准对比都在同一个地方完成。</p>
        </div>
        <ol className="auth-steps">
          <li><b>01</b>上传录像</li>
          <li><b>02</b>自动评分</li>
          <li><b>03</b>评委确认</li>
          <li><b>04</b>报告与排名</li>
        </ol>
      </aside>
      <main className="auth-main">
        <div className="auth-form">
          <h2>登录</h2>
          <p>使用管理员分配的账号登录。</p>
          {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}
          <Form
            layout="vertical"
            requiredMark={false}
            size="large"
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
            <Form.Item name="username" label="用户名" rules={[{ required: true, message: "请输入用户名" }]}>
              <Input autoComplete="username" autoFocus />
            </Form.Item>
            <Form.Item name="password" label="密码" rules={[{ required: true, message: "请输入密码" }]}>
              <Input.Password autoComplete="current-password" />
            </Form.Item>
            <Button type="primary" htmlType="submit" block loading={busy} style={{ marginTop: 4 }}>
              登录
            </Button>
          </Form>
        </div>
      </main>
    </div>
  );
}
