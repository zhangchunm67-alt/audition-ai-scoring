import { Alert, Button, Checkbox, Form, Input, InputNumber, Select, Space, Typography } from "antd";
import type { S } from "../api/client";

type Content = S<"CardContent">;

/** 卖点卡编辑：必讲要点分值合计须等于产品讲解的要点满分（C25）。 */
export default function CardEditor({ initial, required, onSubmit, submitting }: { initial?: Content; required: number; onSubmit: (c: Content) => void; submitting?: boolean }) {
  const [form] = Form.useForm<Content>();
  const checklist = Form.useWatch("checklist", form) as Content["checklist"] | undefined;
  const total = (checklist ?? []).reduce((s, p) => s + (Number(p?.points) || 0), 0);
  const tags = (name: keyof Content, label: string, hint: string) => (
    <Form.Item name={name} label={label} extra={hint}>
      <Select mode="tags" open={false} tokenSeparators={["\n"]} placeholder="输入后回车添加" />
    </Form.Item>
  );
  return (
    <Form form={form} layout="vertical" initialValues={initial ?? { checklist: [{ id: "", name: "", points: 0, compliance_required: false }] }} onFinish={onSubmit}>
      <Typography.Title level={5}>必讲要点</Typography.Title>
      <Alert
        style={{ marginBottom: 12 }}
        type={total === required ? "success" : "error"}
        message={`分值合计 ${total} / ${required}${total === required ? "" : "，须正好等于产品讲解的要点满分才能保存"}`}
      />
      <Form.List name="checklist">
        {(fields, { add, remove }) => (
          <>
            {fields.map((f) => (
              <Space key={f.key} align="baseline" style={{ display: "flex" }}>
                <Form.Item name={[f.name, "id"]} rules={[{ required: true, pattern: /^[A-Za-z0-9_-]{1,64}$/, message: "英文编号" }]}>
                  <Input placeholder="编号，如 deductible" style={{ width: 160 }} />
                </Form.Item>
                <Form.Item name={[f.name, "name"]} rules={[{ required: true, message: "要点名称" }]}>
                  <Input placeholder="要点，如 免赔额" style={{ width: 200 }} />
                </Form.Item>
                <Form.Item name={[f.name, "points"]} rules={[{ required: true }]}>
                  <InputNumber min={0} addonAfter="分" style={{ width: 110 }} />
                </Form.Item>
                <Form.Item name={[f.name, "compliance_required"]} valuePropName="checked">
                  <Checkbox>合规必讲</Checkbox>
                </Form.Item>
                <Button onClick={() => remove(f.name)}>删除</Button>
              </Space>
            ))}
            <Button onClick={() => add({ id: "", name: "", points: 0, compliance_required: false })}>添加要点</Button>
          </>
        )}
      </Form.List>
      <Typography.Title level={5} style={{ marginTop: 24 }}>
        其他内容
      </Typography.Title>
      {tags("targeted_points", "针对性卖点", "O2 针对性对照用，如“儿童医院可以用”")}
      {tags("scenarios", "使用场景", "O3 场景化参考")}
      {tags("banned_phrases", "禁用说法", "讲到即提示，并参与红线检查")}
      <Form.Item label="术语白话对照" extra="O1 语言包装对照用">
        <Form.List name="glossary">
          {(fields, { add, remove }) => (
            <>
              {fields.map((f) => (
                <Space key={f.key} align="baseline" style={{ display: "flex" }}>
                  <Form.Item name={[f.name, "term"]} rules={[{ required: true }]}>
                    <Input placeholder="术语" style={{ width: 160 }} />
                  </Form.Item>
                  <Form.Item name={[f.name, "plain"]} rules={[{ required: true }]}>
                    <Input placeholder="白话解释" style={{ width: 420 }} />
                  </Form.Item>
                  <Button onClick={() => remove(f.name)}>删除</Button>
                </Space>
              ))}
              <Button onClick={() => add()}>添加术语</Button>
            </>
          )}
        </Form.List>
      </Form.Item>
      <Form.Item label="关键数字" extra="L5 事实运用核对用，如 免赔额 = 0 元（以条款为准）">
        <Form.List name="key_numbers">
          {(fields, { add, remove }) => (
            <>
              {fields.map((f) => (
                <Space key={f.key} align="baseline" style={{ display: "flex" }}>
                  <Form.Item name={[f.name, "name"]} rules={[{ required: true }]}>
                    <Input placeholder="名称" style={{ width: 160 }} />
                  </Form.Item>
                  <Form.Item name={[f.name, "value"]} rules={[{ required: true }]}>
                    <Input placeholder="数值" style={{ width: 240 }} />
                  </Form.Item>
                  <Button onClick={() => remove(f.name)}>删除</Button>
                </Space>
              ))}
              <Button onClick={() => add()}>添加数字</Button>
            </>
          )}
        </Form.List>
      </Form.Item>
      <Button type="primary" htmlType="submit" disabled={total !== required} loading={submitting}>
        保存为新版本（草稿）
      </Button>
    </Form>
  );
}
