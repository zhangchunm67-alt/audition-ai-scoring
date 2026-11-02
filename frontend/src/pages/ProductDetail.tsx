import { Button, Card, Collapse, Form, Input, InputNumber, Modal, Select, Space, Switch, Table, Tabs, Tag, Typography } from "antd";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { post, put, type S } from "../api/client";
import { useAuth } from "../auth";
import { msToClock, STATUS_ZH, useAction, useFetch } from "../components/hooks";
import CardEditor from "./CardEditor";

type Card = S<"CardOut">;

function Cards({ pid }: { pid: string }) {
  const { data, reload } = useFetch<Card[]>(`/products/${pid}/cards`);
  const ref = useFetch<S<"RubricDetail">>("/rubrics/reference");
  const { can } = useAuth();
  const act = useAction();
  const [editing, setEditing] = useState(false);
  const latest = data?.[0];
  return (
    <>
      {can("config.write") && !editing && (
        <Button type="primary" style={{ marginBottom: 16 }} onClick={() => setEditing(true)} disabled={!ref.data}>
          {latest ? "基于最新版本修改" : "新建卖点卡"}
        </Button>
      )}
      {ref.error && <Typography.Paragraph type="danger">{ref.error}（请先导入评分标准）</Typography.Paragraph>}
      {editing && ref.data && (
        <Card title="编辑卖点卡" style={{ marginBottom: 16 }} extra={<Button onClick={() => setEditing(false)}>取消</Button>}>
          <CardEditor
            initial={latest?.content}
            required={ref.data.checklist_max}
            onSubmit={async (c) => {
              if (await act(() => post(`/products/${pid}/cards`, c), "已保存为新版本")) {
                setEditing(false);
                reload();
              }
            }}
          />
        </Card>
      )}
      <Collapse
        items={(data ?? []).map((c) => ({
          key: c.id,
          label: (
            <Space>
              第 {c.version} 版<Tag color={c.status === "published" ? "green" : c.status === "draft" ? "orange" : "default"}>{STATUS_ZH[c.status]}</Tag>
              要点合计 {c.points_total} 分
            </Space>
          ),
          extra:
            can("config.write") && c.status === "draft" ? (
              <Button size="small" onClick={async (e) => (e.stopPropagation(), (await act(() => post(`/cards/${c.id}/publish`), "已发布")) && reload())}>
                发布
              </Button>
            ) : null,
          children: (
            <Table
              size="small"
              rowKey="id"
              pagination={false}
              dataSource={c.content.checklist}
              columns={[
                { title: "编号", dataIndex: "id" },
                { title: "要点", dataIndex: "name" },
                { title: "分值", dataIndex: "points" },
                { title: "合规必讲", dataIndex: "compliance_required", render: (v) => (v ? "是" : "—") },
              ]}
            />
          ),
        }))}
      />
    </>
  );
}

function Bank({ pid, kind }: { pid: string; kind: "objections" | "questions" }) {
  const { data, loading, reload } = useFetch<(S<"ObjectionOut"> | S<"QuestionOut">)[]>(`/products/${pid}/${kind}?include_inactive=true`);
  const { can } = useAuth();
  const act = useAction();
  const [edit, setEdit] = useState<Record<string, unknown> | null>(null);
  const [form] = Form.useForm();
  const isObj = kind === "objections";
  const open = (row?: Record<string, unknown>) => {
    form.setFieldsValue(row ?? { active: true });
    setEdit(row ?? {});
  };
  return (
    <>
      {can("config.write") && (
        <Button type="primary" style={{ marginBottom: 16 }} onClick={() => open()}>
          {isObj ? "新增异议" : "新增知识题"}
        </Button>
      )}
      <Table
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={data}
        columns={[
          { title: isObj ? "弹幕原文" : "题目", dataIndex: "text" },
          { title: isObj ? "正确答案要点" : "满分要点", render: (_, r) => ((isObj ? (r as S<"ObjectionOut">).answer_points : (r as S<"QuestionOut">).full_points) ?? []).join("；") },
          { title: "启用", dataIndex: "active", render: (a) => (a ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>) },
          ...(can("config.write") ? [{ title: "", render: (_: unknown, r: object) => <Button size="small" onClick={() => open(r as Record<string, unknown>)}>编辑</Button> }] : []),
        ]}
      />
      <Modal
        title={edit && "id" in edit ? "编辑" : "新增"}
        open={!!edit}
        width={640}
        onCancel={() => setEdit(null)}
        onOk={async () => {
          const v = await form.validateFields();
          const id = edit && "id" in edit ? String(edit.id) : null;
          const ok = await act(() => (id ? put(`/${kind}/${id}`, v) : post(`/products/${pid}/${kind}`, v)), "已保存");
          if (ok) {
            setEdit(null);
            reload();
          }
        }}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="text" label={isObj ? "弹幕原文" : "题目"} rules={[{ required: true }]}>
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name={isObj ? "answer_points" : "full_points"} label={isObj ? "正确答案要点（按条款）" : "满分要点"} rules={isObj ? [] : [{ required: true }]}>
            <Select mode="tags" open={false} placeholder="输入后回车添加" />
          </Form.Item>
          {isObj ? (
            <>
              <Form.Item name="advantages" label="可强调的优势">
                <Select mode="tags" open={false} placeholder="输入后回车添加" />
              </Form.Item>
              <Form.Item name="closing" label="合适的收尾">
                <Input />
              </Form.Item>
            </>
          ) : (
            <Form.Item name="partial_rule" label="部分分条件">
              <Input />
            </Form.Item>
          )}
          <Form.Item name="active" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

function DrawRule({ pid }: { pid: string }) {
  const { data, reload } = useFetch<S<"DrawRuleOut"> | null>(`/products/${pid}/draw-rule`);
  const { can } = useAuth();
  const act = useAction();
  const [form] = Form.useForm();
  if (data === undefined) return null;
  const init = data ? { ...data, objection_times: (data.objection_times_ms ?? []).map(msToClock).join(", ") } : { objection_count: 4, question_count: 6, objection_times: "04:00, 05:30, 07:00, 08:00", prep_seconds: 900, question_seconds: 60, main_seconds: 600 };
  return (
    <Form
      form={form}
      layout="vertical"
      initialValues={init}
      disabled={!can("config.write")}
      style={{ maxWidth: 520 }}
      onFinish={async (v) => {
        const times = String(v.objection_times)
          .split(/[,，\s]+/)
          .filter(Boolean)
          .map((t: string) => {
            const [m, s] = t.split(":").map(Number);
            return (m * 60 + (s || 0)) * 1000;
          });
        const body = { ...v, objection_times_ms: times };
        delete body.objection_times;
        if (await act(() => put(`/products/${pid}/draw-rule`, body), "已保存")) reload();
      }}
    >
      <Typography.Paragraph type="secondary">准备时间和异议弹出时间点按 rubric Q3 默认值，待培训确认后可在此修改。</Typography.Paragraph>
      <Space>
        <Form.Item name="objection_count" label="异议条数">
          <InputNumber min={1} />
        </Form.Item>
        <Form.Item name="question_count" label="知识题数">
          <InputNumber min={1} />
        </Form.Item>
      </Space>
      <Form.Item name="objection_times" label="异议弹出时间点（分:秒，逗号分隔）" rules={[{ required: true }]}>
        <Input />
      </Form.Item>
      <Space>
        <Form.Item name="prep_seconds" label="准备时间（秒）">
          <InputNumber min={0} />
        </Form.Item>
        <Form.Item name="main_seconds" label="主体段（秒）">
          <InputNumber min={60} />
        </Form.Item>
        <Form.Item name="question_seconds" label="每题（秒）">
          <InputNumber min={1} />
        </Form.Item>
      </Space>
      <Button type="primary" htmlType="submit">
        保存
      </Button>
    </Form>
  );
}

export default function ProductDetail() {
  const { id = "" } = useParams();
  const { data } = useFetch<S<"ProductOut">>(`/products/${id}`);
  return (
    <>
      <Typography.Title level={4}>{data?.name}</Typography.Title>
      <Tabs
        items={[
          { key: "card", label: "卖点卡", children: <Cards pid={id} /> },
          { key: "obj", label: "异议库", children: <Bank pid={id} kind="objections" /> },
          { key: "q", label: "知识题库", children: <Bank pid={id} kind="questions" /> },
          { key: "rule", label: "抽题规则", children: <DrawRule pid={id} /> },
        ]}
      />
    </>
  );
}
