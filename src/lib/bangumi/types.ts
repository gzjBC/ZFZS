/**
 * Bangumi 数据类型定义（取自 https://bangumi.github.io/api/ ，只声明本项目用到的字段）。
 * 集中在此文件：下游模块只依赖这里的类型，Bangumi 数据结构变化时只改这里。
 */

export interface SubjectImages {
  large: string;
  common: string;
  medium: string;
  small: string;
  grid: string;
}

export interface SubjectRating {
  total: number;
  count: Record<string, number>;
  score: number;
}

/** 条目（番剧） */
export interface Subject {
  id: number;
  url: string;
  /** 条目类型：2=动画 */
  type: number;
  name: string;
  name_cn: string;
  summary: string;
  /** 开播日期 YYYY-MM-DD */
  air_date: string;
  /** 放送星期 0-6（0=周日） */
  air_weekday: number;
  images: SubjectImages;
  eps: number;
  eps_count: number;
  /** 全站排名（真实数据中位于条目顶层） */
  rank: number;
  rating: SubjectRating;
}

/** /calendar 返回的某一天放送列表 */
export interface CalendarDay {
  weekday: { en: string; cn: string; ja: string; id: number };
  items: Subject[];
}

/** v0 API 条目（GET /v0/subjects、POST /v0/search/subjects），字段与老 API 不同 */
export interface SubjectV0 {
  id: number;
  type: number;
  name: string;
  name_cn: string;
  summary: string;
  /** 放送日期 YYYY-MM-DD 或 null */
  date: string | null;
  platform: string;
  images: SubjectImages;
  total_episodes: number | null;
  eps: number;
  rating: SubjectRating & { count: Record<string, number> };
  score: number | null;
  rank: number | null;
  tags: { name: string; count: number }[];
}

/** v0 分页响应结构 */
export interface PagedSubjects {
  data: SubjectV0[];
  total: number;
  limit: number;
  offset: number;
}
