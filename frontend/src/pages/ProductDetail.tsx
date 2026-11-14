import { Alert, Button, Card, Collapse, Descriptions, Empty, Form, Input, InputNumber, Modal, Select, Space, Table, Tabs, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { post, put, type S } from "../api/client";
import { useAuth } from "../auth";
import { STATUS_ZH, useAction, useFetch } from "../components/hooks";
import { ConfigStatus, PageHeader, Pill } from "../components/ui";
import CardEditor from "./CardEditor";

type Card = S<"CardOut">;

function calibrationState(card: Card) {
  const { fixed_script: script, s2_calibration: cal } = card.content;
  if (!script) return "缺少参考脚本";
  if (!cal || cal.fixed_script_version !== script.version) return "未校准";
  return cal.status === "validated" ? "已验证" : "草稿待验证";
}

function CalibrationTag({ card }: { card: Card }) {
  const label = calibrationState(card);
  return <Pill tone={label === "已验证" ? "ok" : "warn"}>{label}</Pill>;
}

function AdditionalReferences({ card }: { card: Card }) {
  const c = card.content;
  const rows = [
    { name: "必讲要点", values: (c.checklist ?? []).map((p) => `${p.name}（${p.points} 分，仅旧版计分使用）`) },
    { name: "针对性卖点", values: c.targeted_points ?? [] },
    { name: "使用场景", values: c.scenarios ?? [] },
    { name: "术语白话对照", values: (c.glossary ?? []).map((g) => `${g.term}：${g.plain}`) },
    { name: "关键数字", values: (c.key_numbers ?? []).map((n) => `${n.name}：${n.value}`) },
    { name: "禁用说法", values: c.banned_phrases ?? [] },
  ].filter((r) => r.values.length > 0);
  return rows.length ? <Collapse style={{ marginTop: 16 }} items={[{
    key: "extra", label: "附加评分参考",
    children: <Descriptions column={1} size="small">{rows.map((r) => <Descriptions.Item key={r.name} label={r.name}>{r.values.join("；")}</Descriptions.Item>)}</Descriptions>,
  }]} /> : null;
}

function ProductMaterials({ pid }: { pid: string }) {
  const product = useFetch<S<"ProductOut">>(`/products/${pid}`);
  const { data, loading, error, reload } = useFetch<Card[]>(`/products/${pid}/cards`);
  const ref = useFetch<S<"RubricDetail">>("/rubrics/reference");
  const { can } = useAuth();
  const act = useAction();
  const [tab, setTab] = useState("script");
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [viewId, setViewId] = useState<string | null>(null);
  const [calibrating, setCalibrating] = useState(false);
  const latest = data?.[0];
  const published = data?.find((c) => c.status === "published");
  const current = published ?? data?.find((c) => c.status === "draft") ?? latest;
  const viewing = data?.find((c) => c.id === viewId);
  const cal = current?.content.s2_calibration;
  const script = current?.content.fixed_script;

  return (
    <>
      <PageHeader
        back={{ to: "/products", label: "产品资料" }}
        title={product.data?.name ?? "产品资料"}
        tags={product.data?.code && <span className="mono muted">{product.data.code}</span>}
        description="录播按参考脚本评估产品讲解；资料按版本保存，校准状态单独查看。实际观众异议在每条录像中标注。"
      />
      {(error || product.error) && <Alert type="error" message={error || product.error} style={{ marginBottom: 16 }} />}
      <div data-testid="product-material-tabs">
        <Tabs activeKey={tab} onChange={setTab} items={[
          { key: "script", label: "参考脚本", children: <>
            {ref.error && <Alert type="error" message={ref.error} style={{ marginBottom: 16 }} />}
            {can("config.write") && !editing && <Button type="primary" style={{ marginBottom: 16 }} disabled={loading || !ref.data}
              onClick={() => setEditing(true)}>{latest ? "编辑参考脚本" : "添加参考脚本"}</Button>}
            {editing && ref.data ? (
              <Card title="编辑参考脚本" extra={<Button disabled={saving} onClick={() => setEditing(false)}>取消</Button>}>
                <Typography.Paragraph type="secondary">保存会新增一个资料草稿版本；发布后才切换录播使用的资料。修改话术版本后需要重新校准。</Typography.Paragraph>
                <CardEditor initial={latest?.content} required={ref.data.checklist_max} scriptOnly submitting={saving} onSubmit={async (content) => {
                  setSaving(true);
                  try {
                    if (await act(() => post(`/products/${pid}/cards`, content), "已保存为新版本")) {
                      setEditing(false);
                      setTab("versions");
                      reload();
                    }
                  } finally { setSaving(false); }
                }} />
              </Card>
            ) : current ? (
              <Card loading={loading} title={<Space wrap>
                <Typography.Text>{published ? "当前使用" : "资料预览"}：第 {current.version} 版</Typography.Text>
                <ConfigStatus status={current.status} />
                {script && <Typography.Text type="secondary">话术 {script.version}</Typography.Text>}
              </Space>}>
                {!published && <Alert type="info" message="尚未发布可用于录播的资料版本，请在“资料版本”中发布。" style={{ marginBottom: 16 }} />}
                {script ? <div data-testid="reference-script" style={{ whiteSpace: "pre-wrap", lineHeight: 1.9, fontSize: 14.5, maxHeight: "60vh", overflowY: "auto", maxWidth: "80ch" }}>{script.text}</div>
                  : <Empty description="此版本尚无参考脚本，请添加产品的讲解话术。" />}
              </Card>
            ) : <Card loading={loading}><Empty description="尚无参考脚本，添加后保存为资料版本。" /></Card>}
          </> },
          { key: "versions", label: "资料版本", children: <>
            <Typography.Paragraph type="secondary">新增版本保留原资料和已有报告。当前录播使用已发布版本，草稿不会自动替换。</Typography.Paragraph>
            <Table<Card> className="table-card" rowKey="id" size="small" scroll={{ x: 980 }} loading={loading} dataSource={data} pagination={false} columns={[
              { title: "资料版本", width: 170, render: (_, c) => <Space style={{ whiteSpace: "nowrap" }}>第 {c.version} 版{published?.id === c.id && <Tag color="green">当前使用</Tag>}</Space> },
              { title: "状态", width: 110, dataIndex: "status", render: (st) => <ConfigStatus status={st} /> },
              { title: "话术版本", width: 240, render: (_, c) => <Typography.Text style={{ whiteSpace: "nowrap" }}>{c.content.fixed_script?.version ?? "未登记"}</Typography.Text> },
              { title: "校准状态", width: 130, render: (_, c) => <CalibrationTag card={c} /> },
              { title: "创建时间", width: 180, dataIndex: "created_at", render: (t) => <Typography.Text style={{ whiteSpace: "nowrap" }}>{dayjs(t).format("YYYY-MM-DD HH:mm")}</Typography.Text> },
              { title: "操作", width: 190, render: (_, c) => <Space>
                <Button size="small" onClick={() => setViewId(c.id)}>查看版本</Button>
                {can("config.write") && c.status === "draft" && <Button size="small" onClick={async () => {
                  if (await act(() => post(`/cards/${c.id}/publish`), "已发布")) reload();
                }}>发布</Button>}
              </Space> },
            ]} />
          </> },
          { key: "calibration", label: "校准状态", children: current ? <>
            <Card title={<Space>产品讲解校准<CalibrationTag card={current} /></Space>}>
              <Descriptions column={2} size="small">
                <Descriptions.Item label="对应资料">第 {current.version} 版（{STATUS_ZH[current.status]}）</Descriptions.Item>
                <Descriptions.Item label="话术版本">{script?.version ?? "未登记"}</Descriptions.Item>
                <Descriptions.Item label="训练样本">{cal ? `${cal.train_samples} 份` : "未登记"}</Descriptions.Item>
                <Descriptions.Item label="独立验证样本">{cal ? `${cal.holdout_samples} 份` : "未登记"}</Descriptions.Item>
                <Descriptions.Item label="验证一致率">{cal?.holdout_agreement != null ? `${(cal.holdout_agreement * 100).toFixed(1)}%` : "未登记"}</Descriptions.Item>
              </Descriptions>
              {cal && <Typography.Paragraph>产品讲解校准 {cal.version}（{cal.status === "validated" ? "已验证" : "草稿"}）</Typography.Paragraph>}
              {calibrationState(current) !== "已验证" && <Alert type="info" showIcon style={{ marginBottom: 16 }}
                message={!cal ? "尚无校准记录，录播的“产品讲解”由评委打分。" : "校准尚未验证，不能作为正式自动评分依据。"}
                description="没有人工标注样本时无需填写校准表。后续准备训练和独立验证样本，再登记真实的校准结果。" />}
              {can("config.write") && script && current.status !== "retired" && <Button onClick={() => setCalibrating(true)}>{cal ? "更新校准记录" : "登记校准结果"}</Button>}
            </Card>
          </> : <Empty description="添加参考脚本后，可查看对应资料的校准状态。" /> },
        ]} />
      </div>
      <Modal title={viewing ? `资料第 ${viewing.version} 版` : "资料版本"} open={!!viewing} width={900} onCancel={() => setViewId(null)}
        footer={<Button onClick={() => setViewId(null)}>关闭</Button>}>
        {viewing && <>
          <Descriptions size="small" column={2}>
            <Descriptions.Item label="状态">{STATUS_ZH[viewing.status]}</Descriptions.Item>
            <Descriptions.Item label="话术版本">{viewing.content.fixed_script?.version ?? "未登记"}</Descriptions.Item>
            <Descriptions.Item label="校准状态"><CalibrationTag card={viewing} /></Descriptions.Item>
          </Descriptions>
          <Typography.Paragraph style={{ whiteSpace: "pre-wrap", maxHeight: "55vh", overflowY: "auto" }}>{viewing.content.fixed_script?.text ?? "（没有参考脚本）"}</Typography.Paragraph>
          <AdditionalReferences card={viewing} />
        </>}
      </Modal>
      <Modal title="登记产品讲解校准结果" open={calibrating} onCancel={() => setCalibrating(false)} footer={null} width={1100} destroyOnClose>
        {calibrating && current?.content.fixed_script && <Calibration card={current} onSaved={() => { setCalibrating(false); reload(); }} />}
      </Modal>
    </>
  );
}

/** 登记 S2 校准记录（CAL-S2-PRODUCT）：用 20–30 份人工标注样本校准、留出样本验证后填写结论；原始标注另行保存。 */
function Calibration({ card, onSaved }: { card: Card; onSaved: () => void }) {
  const [form] = Form.useForm();
  const act = useAction();
  const cur = card.content.s2_calibration;
  const script = card.content.fixed_script!;
  return (
    <Card size="small" title="销售循环·产品讲解 校准记录" style={{ marginBottom: 12 }}>
      <Form
        form={form}
        layout="inline"
        style={{ rowGap: 12, marginBottom: 12 }}
        initialValues={cur ?? { status: "draft", train_samples: 0, holdout_samples: 0, anchors: [] }}
        onFinish={async (v) => {
          const body = { ...cur, ...v, fixed_script_version: script.version, anchors: cur?.anchors ?? [] };
          if (await act(() => put(`/cards/${card.id}/s2-calibration`, body), "已登记")) onSaved();
        }}
      >
        <Form.Item name="version" label="校准版本" rules={[{ required: true, pattern: /^[A-Za-z0-9_.-]{1,64}$/ }]}>
          <Input style={{ width: 140 }} />
        </Form.Item>
        <Form.Item name="status" label="状态">
          <Select style={{ width: 100 }} options={[{ value: "draft", label: "草稿" }, { value: "validated", label: "已验证" }]} />
        </Form.Item>
        <Form.Item name="train_samples" label="校准样本">
          <InputNumber min={0} />
        </Form.Item>
        <Form.Item name="holdout_samples" label="验证样本">
          <InputNumber min={0} />
        </Form.Item>
        <Form.Item name="holdout_agreement" label="验证一致率">
          <InputNumber min={0} max={1} step={0.01} />
        </Form.Item>
        <Form.Item name="note" label="备注">
          <Input style={{ width: 200 }} />
        </Form.Item>
        <Button htmlType="submit">保存</Button>
      </Form>
      <Typography.Text type="secondary">对应固定话术 {script.version}。标为“已验证”须至少 20 份训练样本、10 份独立验证样本，验证一致率不低于 85%。未验证时继续由评委复核。</Typography.Text>
    </Card>
  );
}


export default function ProductDetail() {
  const { id = "" } = useParams();
  return <ProductMaterials key={id} pid={id} />;
}
