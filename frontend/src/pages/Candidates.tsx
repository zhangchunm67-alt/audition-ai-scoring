import { Button, DatePicker, Descriptions, Drawer, Form, Input, Modal, Select, Space, Table, Tag, Typography, Upload } from "antd";
import type { UploadFile } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";
import { ApiError, patch, post, type S } from "../api/client";
import { useAuth } from "../auth";
import { useAction, useFetch } from "../components/hooks";

type Row = S<"CandidateRow">;
export const HIRING_ZH: Record<string, string> = { undecided: "未定", hired: "已录用", not_hired: "未录用" };

/** 登记书面同意（C30）：同意书版本、签署日期必填，扫描件可选。 */
export async function registerConsent(cid: string, v: { consent_text_version: string; signed_on: Dayjs; attachment?: UploadFile[] }) {
  const fd = new FormData();
  fd.append("consent_text_version", v.consent_text_version);
  fd.append("signed_on", v.signed_on.format("YYYY-MM-DD"));
  const f = v.attachment?.[0]?.originFileObj;
  if (f) fd.append("attachment", f);
  const res = await fetch(`/api/candidates/${cid}/consents`, { method: "POST", credentials: "same-origin", headers: { "X-Requested-With": "fetch" }, body: fd });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, typeof data.detail === "string" ? data.detail : "登记失败，请检查填写内容", data.detail);
  return data as S<"ConsentOut">;
}

export function ConsentForm({ form }: { form: ReturnType<typeof Form.useForm>[0] }) {
  return (
    <Form form={form} layout="vertical" initialValues={{ signed_on: dayjs() }}>
      <Form.Item name="consent_text_version" label="同意书版本" rules={[{ required: true }]} extra="与候选人签署的同意书上印的版本号一致">
        <Input placeholder="如 consent-v1" />
      </Form.Item>
      <Form.Item name="signed_on" label="签署日期" rules={[{ required: true }]}>
        <DatePicker disabledDate={(d) => d.isAfter(dayjs(), "day")} />
      </Form.Item>
      <Form.Item name="attachment" label="扫描件（可选，PDF / JPG / PNG，≤ 10 MB）" valuePropName="fileList" getValueFromEvent={(e) => e?.fileList}>
        <Upload beforeUpload={() => false} maxCount={1} accept=".pdf,.jpg,.jpeg,.png">
          <Button>选择文件</Button>
        </Upload>
      </Form.Item>
    </Form>
  );
}

export function NewCandidateModal({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (c: Row) => void }) {
  const [form] = Form.useForm();
  const act = useAction();
  return (
    <Modal
      title="新建候选人"
      open={open}
      onCancel={onClose}
      onOk={async () => {
        const v = await form.validateFields();
        const c = await act(() => post<Row>("/candidates", { name: v.name, phone: v.phone || null }), "已创建");
        if (c) {
          form.resetFields();
          onCreated(c);
        }
      }}
    >
      <Form form={form} layout="vertical">
        <Form.Item name="name" label="姓名" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item name="phone" label="手机号（可选）" rules={[{ pattern: /^[0-9 +-]{6,20}$/, message: "格式不对" }]}>
          <Input />
        </Form.Item>
      </Form>
    </Modal>
  );
}

function Detail({ id, onChanged }: { id: string; onChanged: () => void }) {
  const { data, reload } = useFetch<S<"CandidateDetail">>(`/candidates/${id}`);
  const { can } = useAuth();
  const act = useAction();
  const [consentOpen, setConsentOpen] = useState(false);
  const [form] = Form.useForm();
  if (!data) return null;
  return (
    <>
      <Descriptions column={1} bordered size="small" style={{ marginBottom: 16 }}>
        <Descriptions.Item label="姓名">{data.name}</Descriptions.Item>
        <Descriptions.Item label="手机号">{data.phone ?? "—"}</Descriptions.Item>
        <Descriptions.Item label="录用状态">
          {can("hiring.update") ? (
            <Select
              value={data.hiring_status}
              style={{ width: 140 }}
              options={Object.entries(HIRING_ZH).map(([value, label]) => ({ value, label }))}
              onChange={async (v) => (await act(() => patch(`/candidates/${id}/hiring`, { hiring_status: v }), "已更新")) && (reload(), onChanged())}
            />
          ) : (
            HIRING_ZH[data.hiring_status]
          )}
        </Descriptions.Item>
      </Descriptions>
      <Typography.Paragraph type="secondary">未录用候选人的视频按保存期限到期自动删除；已录用的保留（正式政策待法务确认）。</Typography.Paragraph>
      <Space style={{ marginBottom: 8 }}>
        <Typography.Title level={5} style={{ margin: 0 }}>
          书面同意登记
        </Typography.Title>
        {can("recording.upload") && <Button onClick={() => setConsentOpen(true)}>登记书面同意</Button>}
      </Space>
      <Table
        size="small"
        rowKey="id"
        pagination={false}
        dataSource={data.consents}
        locale={{ emptyText: "未登记。没有书面同意不能上传录像。" }}
        columns={[
          { title: "同意书版本", dataIndex: "consent_text_version" },
          { title: "签署日期", dataIndex: "signed_on" },
          { title: "扫描件", dataIndex: "attachment_asset_id", render: (a) => (a ? <a href={`/api/media/${a}`} target="_blank" rel="noreferrer">查看</a> : "—") },
          { title: "登记时间", dataIndex: "registered_at", render: (t) => dayjs(t).format("YYYY-MM-DD HH:mm") },
        ]}
      />
      <Modal
        title="登记书面同意"
        open={consentOpen}
        onCancel={() => setConsentOpen(false)}
        onOk={async () => {
          const v = await form.validateFields();
          if (await act(() => registerConsent(id, v), "已登记")) {
            setConsentOpen(false);
            form.resetFields();
            reload();
            onChanged();
          }
        }}
      >
        <ConsentForm form={form} />
      </Modal>
    </>
  );
}

export default function Candidates() {
  const [phone, setPhone] = useState("");
  const { data, loading, reload } = useFetch<Row[]>(`/candidates${phone ? `?phone=${encodeURIComponent(phone)}` : ""}`);
  const { can } = useAuth();
  const [creating, setCreating] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  return (
    <>
      <Typography.Title level={4}>候选人</Typography.Title>
      <Space style={{ marginBottom: 16 }}>
        {can("recording.upload") && (
          <Button type="primary" onClick={() => setCreating(true)}>
            新建候选人
          </Button>
        )}
        <Input.Search placeholder="按手机号查找" allowClear onSearch={setPhone} style={{ width: 240 }} />
      </Space>
      <Table<Row>
        rowKey="id"
        loading={loading}
        dataSource={data}
        onRow={(r) => ({ onClick: () => setOpen(r.id), style: { cursor: "pointer" } })}
        columns={[
          { title: "姓名", dataIndex: "name" },
          { title: "手机号", dataIndex: "phone_masked" },
          { title: "书面同意", dataIndex: "consent_count", render: (n: number) => (n ? <Tag color="green">已登记</Tag> : <Tag color="red">未登记</Tag>) },
          { title: "录像", dataIndex: "recording_count" },
          { title: "录用状态", dataIndex: "hiring_status", render: (s) => HIRING_ZH[s] },
          { title: "创建时间", dataIndex: "created_at", render: (t) => dayjs(t).format("YYYY-MM-DD") },
        ]}
      />
      <NewCandidateModal open={creating} onClose={() => setCreating(false)} onCreated={() => (setCreating(false), reload())} />
      <Drawer title="候选人" width={640} open={!!open} onClose={() => setOpen(null)} destroyOnClose>
        {open && <Detail id={open} onChanged={reload} />}
      </Drawer>
    </>
  );
}
