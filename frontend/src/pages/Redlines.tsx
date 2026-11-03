import { Alert, Button, Card, Collapse, Form, Input, Select, Space, Tag, Typography } from "antd";
import { useState } from "react";
import { post, type S } from "../api/client";
import { useAuth } from "../auth";
import { STATUS_ZH, useAction, useFetch } from "../components/hooks";

type L = S<"LexiconOut">;
const tags = <Select mode="tags" open={false} placeholder="输入后回车添加" />;

export default function Redlines() {
  const { data, reload } = useFetch<L[]>("/redline-lexicons");
  const ref = useFetch<S<"RubricDetail">>("/rubrics/reference");
  const { can } = useAuth();
  const act = useAction();
  const [editing, setEditing] = useState(false);
  const [form] = Form.useForm();
  const latest = data?.[0];
  const ids = Object.keys(latest?.content ?? {}).length ? Object.keys(latest!.content) : ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"];
  return (
    <>
      <Typography.Title level={4}>红线词表与正确说法</Typography.Title>
      <Alert type="info" showIcon style={{ marginBottom: 16 }} message="试镜评分不做合规红线（C33：原始评分表不含合规内容，候选人不是正式员工）。词表保留给以后的直播评分使用。" />
      {!can("redline.write") && <Alert type="info" showIcon style={{ marginBottom: 16 }} message="仅合规角色可以编辑红线词表（PRD M1-5）。" />}
      {can("redline.write") && !editing && (
        <Button
          type="primary"
          style={{ marginBottom: 16 }}
          disabled={!ref.data}
          onClick={() => {
            form.setFieldsValue({ version: "", content: latest?.content ?? {} });
            setEditing(true);
          }}
        >
          {latest ? "基于最新版本修改" : "新建词表"}
        </Button>
      )}
      {editing && (
        <Card title="编辑红线词表（保存为新草稿版本）" style={{ marginBottom: 16 }} extra={<Button onClick={() => setEditing(false)}>取消</Button>}>
          <Form
            form={form}
            layout="vertical"
            onFinish={async (v) => {
              if (await act(() => post("/redline-lexicons", v), "已保存")) {
                setEditing(false);
                reload();
              }
            }}
          >
            <Form.Item name="version" label="版本号" rules={[{ required: true, pattern: /^[A-Za-z0-9_.-]{1,64}$/, message: "字母、数字或 _ . -" }]}>
              <Input placeholder="如 lexicon-2026-11" style={{ width: 280 }} />
            </Form.Item>
            <Collapse
              items={ids.map((rid) => ({
                key: rid,
                forceRender: true,
                label: rid,
                children: (
                  <>
                    <Form.Item name={["content", rid, "name"]} label="红线" rules={[{ required: true }]}>
                      <Input />
                    </Form.Item>
                    <Form.Item name={["content", rid, "keywords"]} label="召回关键词" rules={[{ required: true }]}>
                      {tags}
                    </Form.Item>
                    <Form.Item name={["content", rid, "examples"]} label="命中的典型说法">
                      {tags}
                    </Form.Item>
                    <Form.Item name={["content", rid, "not_redline"]} label="不算红线的说法">
                      {tags}
                    </Form.Item>
                    <Form.Item name={["content", rid, "correct"]} label="正确说法" rules={[{ required: true }]}>
                      {tags}
                    </Form.Item>
                  </>
                ),
              }))}
            />
            <Button type="primary" htmlType="submit" style={{ marginTop: 16 }}>
              保存
            </Button>
          </Form>
        </Card>
      )}
      {(data ?? []).map((l) => (
        <Card
          key={l.id}
          size="small"
          style={{ marginBottom: 12 }}
          title={
            <Space>
              {l.version}
              <Tag color={l.status === "published" ? "green" : l.status === "draft" ? "orange" : "default"}>{STATUS_ZH[l.status]}</Tag>
            </Space>
          }
          extra={
            can("redline.write") && l.status === "draft" ? (
              <Button size="small" onClick={async () => (await act(() => post(`/redline-lexicons/${l.id}/publish`), "已发布")) && reload()}>
                发布
              </Button>
            ) : null
          }
        >
          {Object.entries(l.content).map(([rid, e]) => (
            <Typography.Paragraph key={rid} style={{ marginBottom: 4 }}>
              <Tag>{rid}</Tag>
              {e.name}：{e.keywords.join("、")} → 正确说法：{e.correct.join("；")}
            </Typography.Paragraph>
          ))}
        </Card>
      ))}
    </>
  );
}
