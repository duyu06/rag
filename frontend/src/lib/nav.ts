import { Permission, User, hasAnyPermission } from "@/lib/api";

export type ViewKey =
  | "home"
  | "ask"
  | "search"
  | "knowledge"
  | "retrieval"
  | "trace"
  | "evaluation"
  | "operations"
  | "governance"
  | "system";

export type NavItem = {
  key: ViewKey;
  idx: string;
  zh: string;
  perms: Permission[]; // empty = visible to every signed-in user
};

export const NAV_SECTIONS: { idx: string; zh: string; items: NavItem[] }[] = [
  {
    idx: "01",
    zh: "工作区",
    items: [
      { key: "home", idx: "01", zh: "首页", perms: [] },
      { key: "ask", idx: "02", zh: "问答", perms: ["conversation:read"] },
      { key: "search", idx: "03", zh: "检索", perms: ["knowledge:read"] },
    ],
  },
  {
    idx: "02",
    zh: "知识",
    items: [
      { key: "knowledge", idx: "04", zh: "知识库", perms: ["knowledge:read"] },
    ],
  },
  {
    idx: "03",
    zh: "检索",
    items: [
      { key: "retrieval", idx: "05", zh: "检索实验室", perms: ["retrieval:debug"] },
      { key: "trace", idx: "06", zh: "请求追踪", perms: ["trace:read"] },
    ],
  },
  {
    idx: "04",
    zh: "评测",
    items: [
      { key: "evaluation", idx: "07", zh: "评测", perms: ["evaluation:run"] },
    ],
  },
  {
    idx: "05",
    zh: "运营",
    items: [
      { key: "operations", idx: "08", zh: "运营", perms: ["audit:read", "system:operate"] },
    ],
  },
  {
    idx: "06",
    zh: "治理",
    items: [
      { key: "governance", idx: "09", zh: "治理", perms: ["audit:read", "system:operate", "trace:read:any"] },
    ],
  },
  {
    idx: "07",
    zh: "系统",
    items: [
      { key: "system", idx: "10", zh: "系统", perms: ["system:operate"] },
    ],
  },
];

export function visibleSections(user: User | null) {
  return NAV_SECTIONS.map((section) => ({
    ...section,
    items: section.items.filter((item) => !item.perms.length || hasAnyPermission(user, item.perms)),
  })).filter((section) => section.items.length > 0);
}

export function findNavItem(key: ViewKey) {
  for (const section of NAV_SECTIONS) {
    const item = section.items.find((nav) => nav.key === key);
    if (item) return { section, item };
  }
  return null;
}

export type ViewPayload = {
  query?: string;
  fileName?: string;
  knowledgeBaseId?: string | null;
  conversationId?: string;
  traceId?: string;
  caseId?: string;
};

export type ViewProps = {
  user: User;
  bases: import("@/lib/api").KnowledgeBase[];
  selectedKb: string;
  setSelectedKb: (kb: string) => void;
  navigate: (view: ViewKey, payload?: ViewPayload) => void;
  setNotice: (message: string, kind?: "info" | "err") => void;
  payload?: ViewPayload;
};
