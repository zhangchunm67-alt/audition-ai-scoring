import { Button, Table } from "antd";
import { useState } from "react";
import { Link } from "react-router-dom";
import type { S } from "../api/client";
import { useAuth } from "../auth";
import { useFetch } from "../components/hooks";
import { IconPlus } from "../components/icons";
import NewProductModal from "../components/NewProductModal";
import { PageHeader, Pill } from "../components/ui";

type P = S<"ProductOut">;

export default function Products() {
  const { data, loading, reload } = useFetch<P[]>("/products");
  const { can } = useAuth();
  const [open, setOpen] = useState(false);
  return (
    <>
      <PageHeader
        title="产品资料"
        description="按产品维护参考脚本、资料版本和校准状态。录播中的实际观众问题在录像页标注；按题单试镜的题库和抽题规则从“试镜题单”进入设置。"
        actions={can("config.write") && (
          <Button type="primary" icon={<IconPlus />} onClick={() => setOpen(true)}>
            新建产品
          </Button>
        )}
      />
      <Table<P>
        className="table-card"
        rowKey="id"
        loading={loading}
        dataSource={data}
        pagination={false}
        scroll={{ x: "max-content" }}
        locale={{ emptyText: "还没有产品" }}
        columns={[
          { title: "产品", dataIndex: "name", render: (n, p) => <Link className="cell-main" to={`/products/${p.id}`}>{n}</Link> },
          { title: "编码", dataIndex: "code", render: (c) => <span className="mono muted">{c}</span> },
          { title: "已启用资料版本", dataIndex: "published_card_version", render: (v) => (v ? <Pill tone="ok">第 {v} 版</Pill> : <Pill tone="warn">未启用</Pill>) },
        ]}
      />
      <NewProductModal open={open} onClose={() => setOpen(false)} onCreated={() => {
        setOpen(false);
        reload();
      }} />
    </>
  );
}
