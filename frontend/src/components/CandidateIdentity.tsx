import { Avatar } from "antd";
import { UserOutlined } from "@ant-design/icons";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

type Props = { name: string; phone?: string | null; videoAssetId?: string | null; href?: string; large?: boolean };

/** 只取当前录像画面；不持久化人像，授权失效或媒体删除时回退至人物图标。 */
export default function CandidateIdentity({ name, phone, videoAssetId, href, large }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const [photo, setPhoto] = useState<string>();
  useEffect(() => {
    setPhoto(undefined);
    if (!videoAssetId || !host.current) return;
    let video: HTMLVideoElement | undefined, alive = true;
    const release = () => { if (video) { video.onloadeddata = null; video.onseeked = null; video.onerror = null; video.removeAttribute("src"); video.load(); } };
    const observer = new IntersectionObserver(entries => {
      if (!entries.some(e => e.isIntersecting)) return;
      observer.disconnect();
      video = document.createElement("video"); video.muted = true; video.preload = "auto"; video.playsInline = true;
      const capture = () => {
        if (!alive || !video || !video.videoWidth) return;
        try { const c = document.createElement("canvas"); c.width = 160; c.height = 160; const ctx = c.getContext("2d")!;
          const side = Math.min(video.videoWidth, video.videoHeight);
          ctx.drawImage(video, (video.videoWidth - side) / 2, (video.videoHeight - side) / 2, side, side, 0, 0, 160, 160);
          setPhoto(c.toDataURL("image/jpeg", .8));
        } catch { /* 无法读取时使用默认头像 */ } finally { release(); }
      };
      video.onloadeddata = () => { if (video && video.duration > 1) { video.onseeked = capture; video.currentTime = 1; } else capture(); };
      video.onerror = release; video.src = `/api/media/${videoAssetId}`;
    });
    observer.observe(host.current);
    return () => { alive = false; observer.disconnect(); release(); };
  }, [videoAssetId]);
  return <div className={`candidate-identity ${large ? "large" : ""}`} ref={host}>
    <span title={photo ? "当前报告录像截图" : "暂无可用头像"}><Avatar size={large ? 64 : 44} src={photo} icon={<UserOutlined />} /></span>
    <div className="candidate-identity-text"><strong>{href ? <Link to={href}>{name}</Link> : name}</strong><span>{phone || "未登记电话"}</span></div>
  </div>;
}
