CREATE TABLE IF NOT EXISTS ai_clip_tasks (
  id TEXT PRIMARY KEY,
  source_content_id TEXT NOT NULL,
  source_content_type TEXT NOT NULL,
  source_video_url TEXT NOT NULL,
  title TEXT,
  description TEXT,
  category TEXT,
  tags TEXT NOT NULL DEFAULT '[]',
  target_scenarios TEXT NOT NULL DEFAULT '[]',
  target_durations TEXT NOT NULL DEFAULT '[]',
  target_aspect_ratios TEXT NOT NULL DEFAULT '["9:16"]',
  target_languages TEXT NOT NULL DEFAULT '["zh-CN"]',
  clip_count INTEGER NOT NULL DEFAULT 3,
  status TEXT NOT NULL DEFAULT 'queued',
  progress INTEGER NOT NULL DEFAULT 0,
  current_step TEXT,
  error_message TEXT,
  created_by TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON ai_clip_tasks(status, created_at);

CREATE TABLE IF NOT EXISTS ai_clip_segments (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  source_content_id TEXT NOT NULL,
  start_ms INTEGER NOT NULL,
  end_ms INTEGER NOT NULL,
  duration_ms INTEGER NOT NULL,
  highlight_type TEXT NOT NULL,
  score REAL NOT NULL DEFAULT 0,
  reason TEXT,
  summary TEXT,
  transcript_text TEXT,
  risk_level TEXT NOT NULL DEFAULT 'low',
  risk_reason TEXT,
  packaging_draft TEXT,
  status TEXT NOT NULL DEFAULT 'candidate',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_segments_task ON ai_clip_segments(task_id);

CREATE TABLE IF NOT EXISTS ai_clip_assets (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  segment_id TEXT NOT NULL,
  source_content_id TEXT NOT NULL,
  scenario TEXT NOT NULL,
  duration INTEGER NOT NULL,
  aspect_ratio TEXT NOT NULL,
  language TEXT NOT NULL,
  video_url TEXT NOT NULL,
  cover_url TEXT,
  subtitle_url TEXT,
  title TEXT,
  cover_text TEXT,
  recommendation_text TEXT,
  tags TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'pending_review',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assets_task ON ai_clip_assets(task_id);

-- asset_id intentionally has no FK to ai_clip_assets (single-writer SQLite; existence
-- is checked in code by recordMetrics). Revisit if cross-table deletes are added.
CREATE TABLE IF NOT EXISTS ai_asset_metrics (
  asset_id TEXT PRIMARY KEY,
  impressions INTEGER NOT NULL DEFAULT 0,
  clicks INTEGER NOT NULL DEFAULT 0,
  plays INTEGER NOT NULL DEFAULT 0,
  completions INTEGER NOT NULL DEFAULT 0,
  shares INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
