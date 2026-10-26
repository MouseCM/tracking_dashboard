export type SocialPlatform = 'tiktok' | 'instagram' | 'threads' | 'facebook' | 'youtube';

export interface SocialPost {
  url: string;
  time: string | null;
  caption: string;
  type: string;
  views: number | null;
  likes: number | null;
  comments: number | null;
  shares: number | null;
}

export interface SocialPlatformStats {
  url: string;
  status: 'ok' | 'error' | 'pending' | 'no_link' | 'unsupported';
  error?: string;
  followers?: number | null;
  posts_count?: number | null;
  posts?: SocialPost[];
  api_error?: string; // official API failed this refresh, so the scraper filled in
  connected?: boolean; // Instagram/Facebook only: an OAuth token is stored for this account
}

export interface SocialAccount {
  group: number;
  name: string;
  email: string;
  note: string;
  platforms: Record<SocialPlatform, SocialPlatformStats>;
}

export interface SocialSnapshot {
  fetched_at: string | null;
  refreshing: boolean;
  configured: boolean;
  connect: Partial<Record<SocialPlatform, boolean>>; // platforms whose OAuth app is configured
  accounts: SocialAccount[];
}
