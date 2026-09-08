-- 追番清单表（M2）
-- 同时是 AI 推荐的"看过历史"来源（status=completed + rating）
CREATE TABLE IF NOT EXISTS tracking (
  id                   SERIAL PRIMARY KEY,
  bangumi_subject_id   INT UNIQUE NOT NULL,
  title                TEXT NOT NULL,
  title_cn             TEXT,
  cover_url            TEXT,
  summary              TEXT,
  status               TEXT NOT NULL DEFAULT 'wish'
                       CHECK (status IN ('wish', 'watching', 'completed', 'hold')),
  episode_progress     INT NOT NULL DEFAULT 0,
  total_episodes       INT,
  rating               NUMERIC(3,1),
  air_date             DATE,
  tags                 TEXT[] NOT NULL DEFAULT '{}',
  completed_at         TIMESTAMPTZ,          -- 看完时间（status 变更为 completed 时记录，"已追完"按此分组）
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tracking_status ON tracking (status);
CREATE INDEX IF NOT EXISTS idx_tracking_updated_at ON tracking (updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_tracking_completed_at ON tracking (completed_at DESC);
