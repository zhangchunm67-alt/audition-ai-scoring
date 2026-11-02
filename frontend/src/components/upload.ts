import { ApiError, get, post, type S } from "../api/client";

type UploadOut = S<"UploadOut">;

async function sha256Hex(buf: ArrayBuffer): Promise<string | null> {
  if (!globalThis.crypto?.subtle) return null; // 非安全上下文（http 远程地址）没有 subtle，跳过分片校验头
  const d = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(d), (b) => b.toString(16).padStart(2, "0")).join("");
}

async function putPart(uploadId: string, n: number, buf: ArrayBuffer, signal?: AbortSignal) {
  const sha = await sha256Hex(buf);
  for (let attempt = 1; ; attempt++) {
    try {
      const res = await fetch(`/api/uploads/${uploadId}/parts/${n}`, {
        method: "PUT",
        credentials: "same-origin",
        signal,
        headers: { "X-Requested-With": "fetch", "Content-Type": "application/octet-stream", ...(sha ? { "X-Content-SHA256": sha } : {}) },
        body: buf,
      });
      if (res.ok) return;
      const detail = (await res.json().catch(() => ({}))).detail;
      if (res.status < 500 || attempt >= 4) throw new ApiError(res.status, typeof detail === "string" ? detail : `第 ${n} 片上传失败`, detail);
    } catch (e) {
      if (signal?.aborted || e instanceof ApiError || attempt >= 4) throw e;
    }
    await new Promise((r) => setTimeout(r, 1000 * 2 ** (attempt - 1))); // 网络错误：1s、2s、4s 后重试
  }
}

/** 分片上传，支持断点续传：先问服务端收到了哪些片，只补传缺的；全部到齐后合并。 */
export async function uploadFile(file: File, upload: UploadOut, onProgress: (sent: number, total: number) => void, signal?: AbortSignal) {
  if (file.size !== upload.total_size) throw new Error(`所选文件大小（${file.size} 字节）与这次上传登记的不一致（${upload.total_size} 字节），请选择同一个文件`);
  const st = await get<UploadOut>(`/uploads/${upload.id}`);
  const have = new Set(st.received_parts);
  let sent = st.received_bytes;
  onProgress(sent, file.size);
  for (let n = 1; n <= st.part_count; n++) {
    if (have.has(n)) continue;
    const buf = await file.slice((n - 1) * st.part_size, n * st.part_size).arrayBuffer();
    await putPart(upload.id, n, buf, signal);
    sent += buf.byteLength;
    onProgress(sent, file.size);
  }
  return post<S<"RecordingOut">>(`/uploads/${upload.id}/complete`);
}

export const fmtBytes = (n: number) => (n >= 1024 ** 3 ? `${(n / 1024 ** 3).toFixed(2)} GB` : `${(n / 1024 ** 2).toFixed(1)} MB`);
export const fmtMs = (ms: number | null | undefined) => {
  if (ms == null) return "—";
  const t = ms / 1000;
  return `${String(Math.floor(t / 60)).padStart(2, "0")}:${(t % 60).toFixed(1).padStart(4, "0")}`;
};
