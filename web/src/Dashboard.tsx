import React, { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, ExternalLink } from 'lucide-react';
import { SocialPlatform, SocialPlatformStats, SocialSnapshot } from './types';

const PLATFORMS: { id: SocialPlatform; label: string }[] = [
  { id: 'tiktok', label: 'TikTok' },
  { id: 'instagram', label: 'Instagram' },
  { id: 'threads', label: 'Threads' },
  { id: 'facebook', label: 'Facebook' },
  { id: 'youtube', label: 'YouTube' },
];
const LABEL = Object.fromEntries(PLATFORMS.map((p) => [p.id, p.label])) as Record<SocialPlatform, string>;

const STATUS_TEXT: Record<string, string> = {
  no_link: 'Chưa có link',
  unsupported: 'Chưa hỗ trợ',
  pending: 'Chưa làm mới',
  error: 'Lỗi',
};

const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 2 });
const fmt = (n: number | null | undefined) => (n == null ? '—' : compact.format(n));
const sum = (xs: (number | null | undefined)[]) => xs.reduce<number>((a, x) => a + (x ?? 0), 0);

function ago(iso: string | null | undefined): string {
  if (!iso) return '—';
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 60) return `${Math.max(mins, 0)} phút trước`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)} giờ trước`;
  return `${Math.round(mins / 1440)} ngày trước`;
}
const stamp = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString('vi-VN', { dateStyle: 'short', timeStyle: 'short' }) : '—';

interface Row {
  key: string;
  name: string;
  email: string;
  note: string;
  platform: SocialPlatform;
  stats: SocialPlatformStats;
}

export const Dashboard: React.FC = () => {
  const [data, setData] = useState<SocialSnapshot | null>(null);
  const [error, setError] = useState('');
  const [platform, setPlatform] = useState<SocialPlatform | 'all'>(
    () => (new URLSearchParams(window.location.search).get('platform') as SocialPlatform) || 'all'
  );
  const [open, setOpen] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch('/api/social');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
    } catch (e) {
      setError('Không tải được số liệu tài khoản.');
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // While a refresh runs on the server, poll until it finishes.
  useEffect(() => {
    if (!data?.refreshing) return;
    const t = setTimeout(load, 5000);
    return () => clearTimeout(t);
  }, [data, load]);

  const choosePlatform = (p: SocialPlatform | 'all') => {
    setPlatform(p);
    const url = new URL(window.location.href);
    if (p === 'all') url.searchParams.delete('platform');
    else url.searchParams.set('platform', p);
    window.history.replaceState(null, '', url);
  };

  const rows: Row[] = useMemo(
    () =>
      (data?.accounts ?? []).flatMap((a) =>
        PLATFORMS.filter((p) => platform === 'all' || p.id === platform).map((p) => ({
          key: `${a.group}:${p.id}`,
          name: a.name,
          email: a.email,
          note: a.note,
          platform: p.id,
          stats: a.platforms[p.id],
        }))
      ),
    [data, platform]
  );

  const live = rows.filter((r) => r.stats.status === 'ok');
  const posts = live.flatMap((r) => r.stats.posts ?? []);
  const scope = platform === 'all' ? 'Tất cả nền tảng' : LABEL[platform];

  return (
    <div className="app">
      <main className="main">
        <div className="page-title-row">
          <div className="page-title-left">
            <h1>Tài khoản mạng xã hội</h1>
            <div className="page-subtitle">
              {data?.refreshing
                ? 'Đang làm mới số liệu…'
                : data?.fetched_at
                  ? `Cập nhật ${stamp(data.fetched_at)} · ${data.accounts.length} kênh · tự làm mới 1 lần/ngày khi mở trang`
                  : 'Chưa có số liệu. Chạy: python3 server.py --refresh'}
            </div>
          </div>
          <div className="page-title-actions">
            <div className="segmented-control" role="tablist">
              {[{ id: 'all' as const, label: 'Tất cả' }, ...PLATFORMS].map((p) => (
                <button
                  key={p.id}
                  type="button"
                  role="tab"
                  aria-selected={platform === p.id}
                  className={`seg-chip ${platform === p.id ? 'active' : ''}`}
                  onClick={() => choosePlatform(p.id)}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {error && <div className="social-error">{error}</div>}

        <div className="kpi-row">
          <div className="metric-card metric-card-signal">
            <div className="metric-label">Followers · {scope}</div>
            <div className="metric-value">{fmt(sum(live.map((r) => r.stats.followers)))}</div>
            <div className="metric-sub">{live.length} kênh có số liệu</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Bài đăng · {scope}</div>
            <div className="metric-value">{fmt(sum(live.map((r) => r.stats.posts_count)))}</div>
            <div className="metric-sub">Mới nhất: {ago(posts.map((p) => p.time).filter(Boolean).sort().pop())}</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Lượt xem · {posts.length} bài gần nhất</div>
            <div className="metric-value">{fmt(sum(posts.map((p) => p.views)))}</div>
            <div className="metric-sub">Chỉ tính bài video có lượt xem</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Tương tác · {posts.length} bài gần nhất</div>
            <div className="metric-value">{fmt(sum(posts.map((p) => p.likes)))} like</div>
            <div className="metric-sub">
              {fmt(sum(posts.map((p) => p.comments)))} bình luận · {fmt(sum(posts.map((p) => p.shares)))} chia sẻ
            </div>
          </div>
        </div>

        <div className="panel panel-table">
          <div className="panel-header panel-header-padded">
            <h2>Kênh theo nền tảng</h2>
            <span className="panel-caption">Bấm một dòng để xem từng bài: thời gian đăng, lượt xem, like, bình luận.</span>
          </div>
          <div className="social-table-wrap">
            <table className="data-table social-table">
              <thead>
                <tr>
                  <th>Kênh</th>
                  <th>Nền tảng</th>
                  <th className="num">Followers</th>
                  <th className="num">Bài đăng</th>
                  <th className="num">Lượt xem</th>
                  <th className="num">Like</th>
                  <th className="num">Bình luận</th>
                  <th>Đăng gần nhất</th>
                  <th>Trạng thái</th>
                </tr>
              </thead>
              <tbody>
                {!data && (
                  <tr>
                    <td colSpan={9} className="table-empty">Đang tải…</td>
                  </tr>
                )}
                {rows.map((r) => {
                  const s = r.stats;
                  const ps = s.posts ?? [];
                  const isOpen = open === r.key;
                  const canOpen = ps.length > 0;
                  return (
                    <Fragment key={r.key}>
                      <tr
                        className={canOpen ? 'social-row-clickable' : ''}
                        onClick={() => canOpen && setOpen(isOpen ? null : r.key)}
                        aria-expanded={canOpen ? isOpen : undefined}
                      >
                        <td>
                          <div className="social-entity">
                            {canOpen ? (isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />) : <span className="social-chevron-gap" />}
                            <div>
                              <div className="social-name">{r.name}</div>
                              <div className="social-email">{r.email}</div>
                            </div>
                          </div>
                        </td>
                        <td>
                          {s.url ? (
                            <a className="platform-pill" href={s.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
                              {LABEL[r.platform]} <ExternalLink size={12} />
                            </a>
                          ) : (
                            <span className="platform-pill">{LABEL[r.platform]}</span>
                          )}
                        </td>
                        <td className="num">{fmt(s.followers)}</td>
                        <td className="num">{fmt(s.posts_count)}</td>
                        <td className="num">{s.posts ? fmt(sum(ps.map((p) => p.views))) : '—'}</td>
                        <td className="num">{s.posts ? fmt(sum(ps.map((p) => p.likes))) : '—'}</td>
                        <td className="num">{s.posts ? fmt(sum(ps.map((p) => p.comments))) : '—'}</td>
                        <td className="num">{ago(ps.map((p) => p.time).filter(Boolean).sort().pop())}</td>
                        <td>
                          {s.status === 'ok' ? (
                            <span className="social-status ok">Đã cập nhật</span>
                          ) : (
                            <span className={`social-status ${s.status}`} title={s.error || r.note}>
                              {STATUS_TEXT[s.status]}
                            </span>
                          )}
                          {r.platform === 'tiktok' && r.note && <div className="social-email">{r.note}</div>}
                          {s.connected && (
                            <div className="social-email" title={s.api_error}>
                              {s.api_error ? 'Lỗi API, dùng Apify' : 'Đã kết nối API'}
                            </div>
                          )}
                          {s.connected === false && data?.connect[r.platform] && (
                            <a className="social-email" href={`/api/connect/${r.platform}`} onClick={(e) => e.stopPropagation()}>
                              Kết nối tài khoản
                            </a>
                          )}
                        </td>
                      </tr>
                      {isOpen && (
                        <tr className="social-posts-row">
                          <td colSpan={9}>
                            <table className="data-table social-posts">
                              <thead>
                                <tr>
                                  <th>Thời gian đăng</th>
                                  <th>Loại</th>
                                  <th>Nội dung</th>
                                  <th className="num">Lượt xem</th>
                                  <th className="num">Like</th>
                                  <th className="num">Bình luận</th>
                                  <th className="num">Chia sẻ</th>
                                </tr>
                              </thead>
                              <tbody>
                                {ps.map((p, i) => (
                                  <tr key={p.url || i}>
                                    <td className="num">{stamp(p.time)}</td>
                                    <td>{p.type || '—'}</td>
                                    <td className="social-caption">
                                      {p.url ? (
                                        <a href={p.url} target="_blank" rel="noreferrer">{p.caption || 'Xem bài'}</a>
                                      ) : (
                                        p.caption || '—'
                                      )}
                                    </td>
                                    <td className="num">{fmt(p.views)}</td>
                                    <td className="num">{fmt(p.likes)}</td>
                                    <td className="num">{fmt(p.comments)}</td>
                                    <td className="num">{fmt(p.shares)}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </main>
    </div>
  );
};
