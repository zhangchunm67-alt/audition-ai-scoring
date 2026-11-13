import { Alert, Button, Checkbox, Form, Input, InputNumber, Select, Space, Typography } from "antd";
import type { S } from "../api/client";

type Content = S<"CardContent">;

/** 卖点卡编辑。S2 产品讲解按固定话术的完成准确程度打分（评分表 20261105）：固定话术带版本号，改话术须换版本，
 *  原来的 S2 校准记录随之失效、须重新校准。required 只在旧版评分标准（卖点卡要点 + 结构）下有值：要点分值合计须等于它（C25）。 */
export default function CardEditor({ initial, required, onSubmit, submitting, scriptOnly = false }: { initial?: Content; required: number | null; onSubmit: (c: Content) => void; submitting?: boolean; scriptOnly?: boolean }) {
  const [form] = Form.useForm<Content>();
  const checklist = Form.useWatch("checklist", form) as Content["checklist"] | undefined;
  const scriptVersion = Form.useWatch(["fixed_script", "version"], form) as string | undefined;
  const total = (checklist ?? initial?.checklist ?? []).reduce((s, p) => s + (Number(p?.points) || 0), 0);
  const legacy = required !== null;
  const ok = !legacy || total === required;
  const cal = initial?.s2_calibration;
  const calLost = !!cal && cal.fixed_script_version !== scriptVersion;
  const tags = (name: keyof Content, label: string, hint: string) => (
    <Form.Item name={name} label={label} extra={hint}>
      <Select mode="tags" open={false} tokenSeparators={["\n"]} placeholder="输入后回车添加" />
    </Form.Item>
  );
  return (
    <Form
      form={form}
      layout="vertical"
      initialValues={initial ?? { checklist: [] }}
      onFinish={(c) => {
        const out = { ...initial, ...c, s2_calibration: calLost ? null : cal ?? null };
        if (!out.fixed_script?.version && !out.fixed_script?.text) out.fixed_script = null;
        onSubmit(out);
      }}
    >
      <Typography.Title level={5}>固定话术（销售循环·产品讲解）</Typography.Title>
      <Typography.Paragraph type="secondary">评分表：根据固定话术的完成准确程度打分（满分 50）。试镜缺少固定话术或对应校准记录时不能提交处理；录播缺少这些资料时，“产品讲解”由评委打分。</Typography.Paragraph>
      <Space align="baseline" style={{ display: "flex" }}>
        <Form.Item name={["fixed_script", "version"]} label="话术版本" rules={[{ pattern: /^[A-Za-z0-9_.-]{1,64}$/, message: "英文、数字、点、横线" }]}>
          <Input placeholder="如 script-2026-11" style={{ width: 200 }} />
        </Form.Item>
      </Space>
      <Form.Item name={["fixed_script", "text"]} label="话术全文">
        <Input.TextArea rows={6} placeholder="该产品的固定讲解话术" />
      </Form.Item>
      {calLost && <Alert style={{ marginBottom: 12 }} type="warning" message={`话术版本已改，原产品讲解校准记录（${cal?.version}）不再适用，保存后须重新校准`} />}
      {scriptOnly && !ok && <Alert type="warning" style={{ marginBottom: 12 }} message="参照的旧版评分标准需要完整要点资料，请先导入并使用现行评分配置。" />}
      {!scriptOnly && <>
      <Typography.Title level={5}>必讲要点</Typography.Title>
      {legacy ? (
        <Alert
          style={{ marginBottom: 12 }}
          type={ok ? "success" : "error"}
          message={`旧版评分标准：分值合计 ${total} / ${required}${ok ? "" : "，须正好等于产品讲解的要点满分才能保存"}`}
        />
      ) : (
        <Typography.Paragraph type="secondary">新版评分标准不按要点计分，要点只用于题单上的讲解提示。</Typography.Paragraph>
      )}
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
      </>}
      <Button type="primary" htmlType="submit" disabled={!ok} loading={submitting}>
        保存为新版本（草稿）
      </Button>
    </Form>
  );
}
