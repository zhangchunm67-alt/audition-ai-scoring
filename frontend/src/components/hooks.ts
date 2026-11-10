import { App } from "antd";
import { useCallback, useEffect, useState } from "react";
import { ApiError, get } from "../api/client";

/** 读取接口数据；reload() 重新拉取。 */
export function useFetch<T>(path: string | null) {
  const [data, setData] = useState<T | undefined>();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!path) return;
    let alive = true;
    setLoading(true);
    get<T>(path)
      .then((d) => alive && (setData(d), setError(null)))
      .catch((e: Error) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [path, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}

/** 执行写操作，成功提示、失败弹出后端给的原因。 */
export function useAction() {
  const { message } = App.useApp();
  return useCallback(
    async <T,>(fn: () => Promise<T>, ok?: string): Promise<T | undefined> => {
      try {
        const r = await fn();
        if (ok) message.success(ok);
        return r;
      } catch (e) {
        message.error(e instanceof ApiError ? e.message : String(e), 6);
        return undefined;
      }
    },
    [message],
  );
}

export const msToClock = (ms: number) => {
  const s = Math.round(ms / 1000);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
};

export const STATUS_ZH: Record<string, string> = { draft: "草稿", published: "已发布", retired: "已停用", issued: "未使用", used: "已使用", void: "已作废" };
export const ROLE_ZH: Record<string, string> = { admin: "管理员", compliance: "合规", calibrator: "校准员", hr: "HR", anchor: "新主播" };
export const MODE_ZH: Record<string, string> = { audition: "试镜", live: "录播" };
export const AUDIENCE_ZH: Record<string, string> = { veteran: "老主播", month_1: "上播 1 个月", new_trial: "新主播内部试播" };
