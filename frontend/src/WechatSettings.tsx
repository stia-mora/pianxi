import { useState } from "react";
import { Check, FlaskConical, Loader2, Save } from "lucide-react";
import { api, post } from "./api";

export default function WechatSettings({
  initialUrl,
  hasToken,
  notify,
}: {
  initialUrl: string;
  hasToken: boolean;
  notify: (message: string) => void;
}) {
  const [url, setUrl] = useState(initialUrl);
  const [token, setToken] = useState("");
  const [clearToken, setClearToken] = useState(false);
  const [savedToken, setSavedToken] = useState(hasToken);
  const [busy, setBusy] = useState("");
  const [status, setStatus] = useState<{ ok: boolean; message: string } | null>(
    null,
  );
  return (
    <form
      className="settings-section"
      onSubmit={async (event) => {
        event.preventDefault();
        setBusy("save");
        setStatus(null);
        try {
          await api("/settings/wechat", {
            method: "PUT",
            body: JSON.stringify({
              url,
              token: clearToken ? "" : token || undefined,
            }),
          });
          setSavedToken(!clearToken && (!!token || savedToken));
          setToken("");
          setClearToken(false);
          notify("视频号连接已保存");
        } catch (error) {
          setStatus({ ok: false, message: (error as Error).message });
        } finally {
          setBusy("");
        }
      }}
    >
      <div className="settings-label">
        <h2>微信视频号</h2>
        <p>连接运行 wx_channel 的微信电脑，获取视频后自动下载、转写和分析。</p>
      </div>
      <div className="settings-fields">
        <p className="muted">
          微信电脑需运行 wx_channel，并保持已登录的视频号分享页在线。普通 Cookie
          无法代替微信页面会话。
        </p>
        <label>
          采集器地址
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="http://127.0.0.1:2025"
            maxLength={500}
          />
        </label>
        <small className="muted">
          地址以片析后端所在机器为准。服务器部署时需连接到微信电脑，远程连接使用
          HTTPS。
        </small>
        <label>
          连接令牌（可选）
          <input
            type="password"
            autoComplete="new-password"
            value={token}
            onChange={(e) => {
              setToken(e.target.value);
              setClearToken(false);
            }}
            placeholder={
              savedToken ? "已配置，留空保留" : "wx_channel 的 secret_token"
            }
            maxLength={2000}
            disabled={clearToken}
          />
        </label>
        {savedToken && (
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={clearToken}
              onChange={(e) => setClearToken(e.target.checked)}
            />
            清除已保存的连接令牌
          </label>
        )}
        <div className="settings-actions">
          <button className="primary" disabled={!!busy}>
            {busy === "save" ? (
              <Loader2 size={16} className="spin" />
            ) : (
              <Save size={16} />
            )}
            保存视频号连接
          </button>
          <button
            type="button"
            className="secondary"
            disabled={!!busy}
            onClick={async () => {
              setBusy("test");
              setStatus(null);
              try {
                setStatus(
                  await post<{ ok: boolean; message: string }>(
                    "/settings/test-wechat",
                  ),
                );
              } catch (error) {
                setStatus({ ok: false, message: (error as Error).message });
              } finally {
                setBusy("");
              }
            }}
          >
            {busy === "test" ? (
              <Loader2 size={16} className="spin" />
            ) : (
              <FlaskConical size={16} />
            )}
            检测已保存连接
          </button>
        </div>
        {status && (
          <p
            className={`test-result ${status.ok ? "ok" : "failed"}`}
            role="status"
          >
            {status.ok && <Check size={14} />}
            {status.message}
          </p>
        )}
      </div>
    </form>
  );
}
