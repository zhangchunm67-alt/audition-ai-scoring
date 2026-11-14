import { Button, DatePicker, Descriptions, Drawer, Form, Input, Modal, Select, Space, Table, Tag, Typography, Upload } from "antd";
import type { UploadFile } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";
import { ApiError, patch, post, put, type S } from "../api/client";
import { useAuth } from "../auth";
import { useAction, useFetch } from "../components/hooks";
import { IconPlus } from "../components/icons";
import { PageHeader, Pill, Toolbar, type Tone } from "../components/ui";

type Row = S<"CandidateRow">;
export const HIRING_ZH: Record<string, string> = { undecided: "未定", hired: "已录用", not_hired: "未录用" };
const HIRING_TONE: Record<string, Tone> = { undecided: "neutral", hired: "ok", not_hired: "bad" };

/** 书面同意登记 UI 暂隐；上传时仍会自动补占位登记以满足后端 C30。改回 true 即可恢复界面。 */
export const SHOW_CONSENT_UI = false;

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

/** 确保候选人有一条书面同意：已有则复用最新一条，否则自动登记占位版本。 */
export async function ensureConsent(cid: string, existing: S<"ConsentOut">[] = []) {
  if (existing.length) return existing[0];
  return registerConsent(cid, { consent_text_version: "deferred-pending-legal", signed_on: dayjs() });
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
      <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
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

/** 已录用的新主播：关联本人账号后，该账号只能看到本人的试镜记录（C31）。 */
function AnchorLink({ id, current, onChanged }: { id: string; current: string | null; onChanged: () => void }) {
  const { data } = useFetch<S<"UserOut">[]>("/users/anchors");
  const act = useAction();
  return (
    <Descriptions column={1} size="small" style={{ marginBottom: 16 }}>
      <Descriptions.Item label="关联新主播账号">
        <Select allowClear placeholder="录用后关联本人的“新主播”账号" style={{ width: 280 }} value={current ?? undefined}
          options={(data ?? []).map((u) => ({ value: u.id, label: `${u.display_name}（${u.username}）` }))}
          onChange={async (v) => (await act(() => put(`/candidates/${id}/linked-user`, { user_id: v ?? null }), v ? "已关联" : "已解除关联")) && onChanged()} />
      </Descriptions.Item>
    </Descriptions>
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
      {can("hiring.update") && <AnchorLink id={id} current={data.linked_user_id ?? null} onChanged={() => (reload(), onChanged())} />}
      {SHOW_CONSENT_UI && (
        <>
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
      )}
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
      <PageHeader
        title="候选人"
        description="点一行查看候选人的录用状态，并在录用后关联本人的新主播账号。"
        actions={can("recording.upload") && (
          <Button type="primary" icon={<IconPlus />} onClick={() => setCreating(true)}>
            新建候选人
          </Button>
        )}
      />
      <Toolbar>
        <Input.Search placeholder="按手机号查找" allowClear onSearch={setPhone} style={{ width: 260 }} />
      </Toolbar>
      <Table<Row>
        className="table-card is-clickable"
        scroll={{ x: "max-content" }}
        pagination={{ pageSize: 20, hideOnSinglePage: true, showSizeChanger: false }}
        locale={{ emptyText: phone ? "没有找到这个手机号的候选人" : "还没有候选人" }}
        rowKey="id"
        loading={loading}
        dataSource={data}
        onRow={(r) => ({ onClick: () => setOpen(r.id) })}
        columns={[
          { title: "姓名", dataIndex: "name", render: (n: string) => <span className="cell-main">{n}</span> },
          { title: "手机号", dataIndex: "phone_masked", render: (p: string | null) => (p ? <span className="mono">{p}</span> : <span className="faint">—</span>) },
          ...(SHOW_CONSENT_UI
            ? [{ title: "书面同意", dataIndex: "consent_count", render: (n: number) => (n ? <Tag color="green">已登记</Tag> : <Tag color="red">未登记</Tag>) }]
            : []),
          { title: "录像", dataIndex: "recording_count", render: (n: number) => <span className="num">{n} 条</span> },
          { title: "录用状态", dataIndex: "hiring_status", render: (s: string) => <Pill tone={HIRING_TONE[s] ?? "neutral"}>{HIRING_ZH[s]}</Pill> },
          { title: "创建时间", dataIndex: "created_at", render: (t: string) => <span className="cell-time">{dayjs(t).format("YYYY-MM-DD")}</span> },
        ]}
      />
      <NewCandidateModal open={creating} onClose={() => setCreating(false)} onCreated={() => (setCreating(false), reload())} />
      <Drawer title="候选人" width={640} open={!!open} onClose={() => setOpen(null)} destroyOnClose>
        {open && <Detail id={open} onChanged={reload} />}
      </Drawer>
    </>
  );
}
