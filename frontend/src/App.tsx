import { Button, Layout, Menu, Space, Spin, Typography } from "antd";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "./auth";
import { ROLE_ZH } from "./components/hooks";
import AuditLogs from "./pages/AuditLogs";
import Candidates from "./pages/Candidates";
import NewRecording from "./pages/NewRecording";
import RecordingDetail from "./pages/RecordingDetail";
import Recordings from "./pages/Recordings";
import SheetPrint from "./pages/SheetPrint";
import Login from "./pages/Login";
import ProductDetail from "./pages/ProductDetail";
import Products from "./pages/Products";
import ReadingScripts from "./pages/ReadingScripts";
import Redlines from "./pages/Redlines";
import RubricDetail from "./pages/RubricDetail";
import Rubrics from "./pages/Rubrics";
import SheetDetail from "./pages/SheetDetail";
import Sheets from "./pages/Sheets";
import Users from "./pages/Users";

const NAV = [
  { key: "/rubrics", label: "评分标准", perm: "config.read" },
  { key: "/products", label: "产品与题库", perm: "config.read" },
  { key: "/reading-scripts", label: "朗读稿", perm: "config.read" },
  { key: "/redlines", label: "红线词表", perm: "redline.read" },
  { key: "/sheets", label: "试镜题单", perm: "sheet.read" },
  { key: "/candidates", label: "候选人", perm: "report.read_all" },
  { key: "/recordings", label: "试镜录像", perm: "report.read_all" },
  { key: "/users", label: "账号管理", perm: "users.manage" },
  { key: "/audit", label: "审计日志", perm: "audit.read" },
];

export default function App() {
  const { me, loading, logout, can } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  if (loading) return <Spin style={{ margin: 80 }} />;
  if (!me) return <Login />;
  if (/^\/sheets\/[^/]+\/print$/.test(loc.pathname)) {
    return (
      <Routes>
        <Route path="/sheets/:id/print" element={<SheetPrint />} />
      </Routes>
    );
  }
  const items = NAV.filter((n) => can(n.perm));
  const selected = items.find((n) => loc.pathname.startsWith(n.key))?.key;
  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Layout.Sider width={200} theme="light">
        <Typography.Title level={5} style={{ padding: "16px 20px", margin: 0 }}>
          试镜评分后台
        </Typography.Title>
        <Menu mode="inline" selectedKeys={selected ? [selected] : []} items={items} onClick={(e) => nav(e.key)} />
      </Layout.Sider>
      <Layout>
        <Layout.Header style={{ background: "#fff", display: "flex", justifyContent: "flex-end", paddingInline: 24 }}>
          <Space>
            <span>
              {me.display_name}（{ROLE_ZH[me.role] ?? me.role}）
            </span>
            <Button onClick={logout}>退出</Button>
          </Space>
        </Layout.Header>
        <Layout.Content style={{ padding: 24 }}>
          <Routes>
            <Route path="/" element={<Navigate to={items[0]?.key ?? "/"} replace />} />
            <Route path="/rubrics" element={<Rubrics />} />
            <Route path="/rubrics/:id" element={<RubricDetail />} />
            <Route path="/products" element={<Products />} />
            <Route path="/products/:id" element={<ProductDetail />} />
            <Route path="/reading-scripts" element={<ReadingScripts />} />
            <Route path="/redlines" element={<Redlines />} />
            <Route path="/sheets" element={<Sheets />} />
            <Route path="/sheets/:id" element={<SheetDetail />} />
            <Route path="/candidates" element={<Candidates />} />
            <Route path="/recordings" element={<Recordings />} />
            <Route path="/recordings/new" element={<NewRecording />} />
            <Route path="/recordings/:id" element={<RecordingDetail />} />
            <Route path="/users" element={<Users />} />
            <Route path="/audit" element={<AuditLogs />} />
            <Route path="*" element={<Typography.Text>页面不存在</Typography.Text>} />
          </Routes>
        </Layout.Content>
      </Layout>
    </Layout>
  );
}
