import { Form, Input, Modal } from "antd";
import { useState } from "react";
import { post, type S } from "../api/client";
import { useAction } from "./hooks";

export default function NewProductModal({ open, onClose, onCreated }: {
  open: boolean;
  onClose: () => void;
  onCreated: (product: S<"ProductOut">) => void;
}) {
  const [form] = Form.useForm<S<"ProductIn">>();
  const [saving, setSaving] = useState(false);
  const act = useAction();
  return (
    <Modal title="新建产品" open={open} confirmLoading={saving} closable={!saving} maskClosable={!saving}
      onCancel={() => !saving && onClose()} onOk={() => form.submit()}>
      <Form form={form} layout="vertical" disabled={saving} onFinish={async (values) => {
        if (saving) return;
        setSaving(true);
        try {
          const product = await act(() => post<S<"ProductOut">>("/products", values), "已创建产品");
          if (product) {
            form.resetFields();
            onCreated(product);
          }
        } finally {
          setSaving(false);
        }
      }}>
        <Form.Item name="name" label="产品名称" rules={[{ required: true, whitespace: true, message: "请输入产品名称" }]}>
          <Input maxLength={128} />
        </Form.Item>
        <Form.Item name="code" label="编码" rules={[{ required: true, pattern: /^[A-Za-z0-9_-]{2,64}$/, message: "2–64 位字母、数字、_ 或 -" }]}>
          <Input />
        </Form.Item>
      </Form>
    </Modal>
  );
}
