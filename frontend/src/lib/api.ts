// Hand-written to match backend/app/schemas/api.py and schemas/ai.py. Money is integer minor units.

export type Health = {
  status: string;
  paypal: { environment: string; configured: boolean; token_ok: boolean | null };
  judge_mode: boolean;
};

export type Provenance = "explicit" | "inferred" | "unknown";
export type Classification = "in_scope" | "exceeds_limit" | "out_of_scope" | "question";

export type ExtractedField = {
  value: string | null;
  provenance: Provenance;
  quote: string;
  quote_verified: boolean;
  needs_confirmation: boolean;
};

export type IntakeAnalysis = {
  source_language: string;
  title: ExtractedField;
  deliverables: ExtractedField[];
  file_formats: ExtractedField[];
  deadline: ExtractedField;
  revisions: ExtractedField;
  usage_rights: ExtractedField;
  budget: ExtractedField;
  budget_minor_units: number | null;
  currency_code: string | null;
  client_email: ExtractedField;
  sketch_review_requested: ExtractedField;
  questions: string[];
  reply_draft_client: string;
  reply_draft_seller_translation: string;
  source: "live" | "cached";
  model_id: string | null;
};

export type ScopeGuardItem = {
  request_summary: string;
  quote: string;
  quote_verified: boolean;
  classification: Classification;
  clause_ref: string | null;
  clause_text: string | null;
  rate_card_code: string | null;
  quantity: number;
  unit_price_minor_units: number | null;
  amount_minor_units: number | null;
  needs_price: boolean;
  billable: boolean;
};

export type ScopeGuardResult = {
  items: ScopeGuardItem[];
  total_minor_units: number;
  reply_draft_client: string;
  reply_draft_seller_translation: string;
  source: "live" | "cached";
  model_id: string | null;
};

export type ScopeFields = {
  title?: string | null;
  description?: string | null;
  client_display_name?: string | null;
  client_email?: string | null;
  source_language?: string | null;
  currency_code?: string | null;
  deliverables?: string[] | null;
  file_formats?: string[] | null;
  revisions_included?: number | null;
  deadline_date?: string | null;
  usage_rights?: string | null;
  total_minor_units?: number | null;
};

export type ProjectPatch = ScopeFields & { intake?: { message: string; analysis: IntakeAnalysis } };

export type MilestonePlanEntry = {
  title: string;
  basis_points: number;
  billing_trigger: "ON_AGREEMENT" | "ON_DELIVERY_APPROVED";
};

export type RateCardItem = {
  code: string;
  name: string;
  unit_price_minor_units: number;
  unit: string;
  active: boolean;
};
export type RateCard = { currency_code: string; items: RateCardItem[] };

export type Invoice = {
  id: string;
  milestone_id: string;
  is_active: boolean;
  attempt: number;
  invoice_number: string;
  paypal_invoice_id: string | null;
  amount_minor_units: number;
  currency_code: string;
  billed_scope_version: number;
  paypal_status: string | null;
  status_label: string;
  settles_milestone: boolean;
  needs_attention: boolean;
  payer_link: string | null;
  last_synced_at: string | null;
  last_error_code: string | null;
  reminders_sent: number;
  sent_at: string | null;
  paid_seen_at: string | null;
};

export type MilestoneState =
  | "LOCKED"
  | "AWAITING_DELIVERY"
  | "DELIVERED"
  | "APPROVED"
  | "READY_TO_BILL"
  | "BILLED"
  | "SETTLED";

export type Milestone = {
  id: string;
  position: number;
  title: string;
  kind: "plan" | "change_order";
  change_order_id: string | null;
  percentage_basis_points: number | null;
  amount_minor_units: number;
  billing_trigger: string;
  workflow_state: MilestoneState;
  evidence_url: string | null;
  evidence_note: string | null;
  delivered_at: string | null;
  approved_at: string | null;
  active_invoice_id: string | null;
  flagged: boolean;
};

export type ChangeOrderLine = {
  id: string;
  request_summary: string | null;
  quote: string | null;
  classification: Classification | null;
  clause_ref: string | null;
  clause_text: string | null;
  rate_card_code: string | null;
  name: string;
  quantity: number;
  unit_price_minor_units: number | null;
  amount_minor_units: number | null;
  needs_price: boolean;
  price_source: string | null;
};

export type ChangeOrder = {
  id: string;
  number: number;
  message_id: string;
  status: "DRAFT" | "SELLER_APPROVED" | "CLIENT_APPROVED" | "DECLINED" | "SUPERSEDED";
  lines: ChangeOrderLine[];
  total_minor_units: number;
  base_scope_version: number;
  resulting_scope_version: number | null;
  created_at: string;
};

export type ProposalKind =
  | "BILL_MILESTONE"
  | "SEND_INVOICE"
  | "SEND_REMINDER"
  | "CHANGE_ORDER"
  | "CANCEL_INVOICE";
export type ProposalStatus = "PENDING" | "APPROVED" | "EXECUTED" | "FAILED" | "DISMISSED" | "STALE";

export type Blocker = { code: string; message: string };

export type NotBilled = {
  request_summary: string;
  classification: Classification;
  quote: string;
  clause_ref: string | null;
};

export type Proposal = {
  id: string;
  project_id: string;
  kind: ProposalKind;
  status: ProposalStatus;
  payload: {
    milestone_id?: string;
    milestone_title?: string;
    recipient_email?: string | null;
    amount_minor_units?: number;
    currency_code?: string;
    scope_version?: number;
    note?: string;
    subject?: string;
    terms_and_conditions?: string;
    invoice_id?: string;
    invoice_number?: string;
    paypal_invoice_id?: string | null;
    billed_scope_version?: number;
    change_order_id?: string;
    number?: number;
    lines?: ChangeOrderLine[];
    not_billed?: NotBilled[];
    [key: string]: unknown;
  };
  rationale: string;
  evidence: Record<string, unknown>[];
  scope_version: number;
  target_ref: string;
  target_state: string;
  idempotency_key: string;
  model_id: string | null;
  blockers: Blocker[];
  can_approve: boolean;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  decided_at: string | null;
  executed_at: string | null;
};

export type Activity = {
  id: string;
  actor: "agent" | "seller" | "client" | "paypal" | "system";
  action: string;
  details: Record<string, unknown>;
  created_at: string;
};

export type Message = {
  id: string;
  kind: "intake" | "follow_up";
  body: string;
  language: string | null;
  received_at: string;
  analysis: Record<string, unknown> | null;
};

export type CommissionStatus =
  | "DRAFT"
  | "AWAITING_ACCEPTANCE"
  | "AGREED"
  | "IN_PROGRESS"
  | "COMPLETED"
  | "CANCELLED";

export type Scope = {
  id: string;
  title: string;
  description: string;
  client_display_name: string;
  client_email: string | null;
  seller_display_name: string;
  source_language: string;
  currency_code: string;
  deliverables: string[];
  file_formats: string[];
  revisions_included: number | null;
  revisions_used: number;
  deadline_date: string | null;
  usage_rights: string;
  total_minor_units: number | null;
  change_order_total_minor_units: number;
  scope_version: number;
  status: CommissionStatus;
  seller_accepted_version: number | null;
  client_accepted_version: number | null;
  created_at: string;
  updated_at: string;
};

export type Project = Scope & {
  share_token: string;
  client_path: string;
  missing_fields: string[];
  billing_disabled_code: string | null;
  milestones: Milestone[];
  invoices: Invoice[];
  proposals: Proposal[];
  change_orders: ChangeOrder[];
  messages: Message[];
  activity: Activity[];
};

export type FollowUp = {
  message_id: string;
  scope_guard: ScopeGuardResult;
  change_order: ChangeOrder | null;
  proposal: Proposal | null;
  project: Project;
};

export type ClientInvoice = {
  invoice_number: string;
  amount_minor_units: number;
  currency_code: string;
  paypal_status: string | null;
  status_label: string;
  payer_link: string | null;
};

export type ClientMilestone = {
  id: string;
  position: number;
  title: string;
  kind: "plan" | "change_order";
  amount_minor_units: number;
  workflow_state: MilestoneState;
  evidence_url: string | null;
  evidence_note: string | null;
  delivered_at: string | null;
  approved_at: string | null;
  invoice: ClientInvoice | null;
  can_approve: boolean;
};

export type ClientChangeOrder = {
  id: string;
  number: number;
  status: ChangeOrder["status"];
  lines: ChangeOrderLine[];
  total_minor_units: number;
  can_decide: boolean;
};

export type ClientView = Scope & {
  seller_accepted: boolean;
  client_accepted: boolean;
  can_accept: boolean;
  milestones: ClientMilestone[];
  change_orders: ClientChangeOrder[];
};

export type DemoReset = {
  project: Project;
  suggested_client_email: string | null;
  example_messages: { intake: string; follow_up: string };
};

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: Record<string, unknown>,
    public requestId?: string,
  ) {
    super(message);
  }

  /** PayPal-side failures mark the proposal FAILED; the card shows a retry. */
  get proposalFailed(): boolean {
    return this.details?.proposal_status === "FAILED";
  }
}

/** A new key per user action. A retry after a failure must call this again. */
export function newKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && !path.startsWith("/api/analyze") && !/\/invoices\/[^/]+\/refresh$/.test(path)) {
    headers["Idempotency-Key"] = newKey();
  }
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "NETWORK", "Cannot reach the server. Check your connection and try again.");
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new ApiError(
      response.status,
      data.code ?? "HTTP_ERROR",
      data.message ?? response.statusText,
      data.details,
      data.request_id,
    );
  }
  return response.json() as Promise<T>;
}

const get = <T>(path: string) => request<T>("GET", path);
const post = <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {});

export const api = {
  health: () => get<Health>("/api/health"),
  demoReset: () => post<DemoReset>("/api/demo/reset"),
  analyze: (message: string) => post<IntakeAnalysis>("/api/analyze", { message }),
  project: (id: string) => get<Project>(`/api/projects/${id}`),
  projects: () => get<{ id: string; title: string; status: string }[]>("/api/projects"),
  patchProject: (id: string, body: ProjectPatch) => request<Project>("PATCH", `/api/projects/${id}`, body),
  putMilestones: (id: string, milestones: MilestonePlanEntry[]) =>
    request<Project>("PUT", `/api/projects/${id}/milestones`, { milestones }),
  sellerAccept: (id: string, scopeVersion: number) =>
    post<Project>(`/api/projects/${id}/accept`, { scope_version: scopeVersion }),
  logRevision: (id: string) => post<Project>(`/api/projects/${id}/revisions`, { count: 1 }),
  postMessage: (id: string, body: string, language?: string) =>
    post<FollowUp>(`/api/projects/${id}/messages`, { body, language }),
  deliver: (milestoneId: string, note?: string) =>
    post<Project>(`/api/milestones/${milestoneId}/deliver`, note ? { note } : {}),
  proposeBill: (milestoneId: string) => post<Proposal>(`/api/milestones/${milestoneId}/propose-bill`),
  approveProposal: (id: string) => post<Proposal>(`/api/proposals/${id}/approve`),
  dismissProposal: (id: string) => post<Proposal>(`/api/proposals/${id}/dismiss`),
  editProposal: (
    id: string,
    body: {
      note?: string;
      subject?: string;
      lines?: { id: string; quantity?: number; unit_price_minor_units?: number }[];
      remove_line_ids?: string[];
    },
  ) => request<Proposal>("PATCH", `/api/proposals/${id}`, body),
  refreshInvoice: (id: string) => post<Invoice>(`/api/invoices/${id}/refresh`),
  cancelInvoice: (id: string) => post<Proposal>(`/api/invoices/${id}/cancel`),
  rateCard: () => get<RateCard>("/api/settings/rate-card"),
  putRateCard: (items: RateCardItem[]) => request<RateCard>("PUT", "/api/settings/rate-card", { items }),
  clientView: (token: string) => get<ClientView>(`/api/c/${token}`),
  clientAccept: (token: string, scopeVersion: number) =>
    post<ClientView>(`/api/c/${token}/accept`, { scope_version: scopeVersion }),
  clientApproveMilestone: (token: string, milestoneId: string) =>
    post<ClientView>(`/api/c/${token}/milestones/${milestoneId}/approve`),
  clientApproveChangeOrder: (token: string, id: string) =>
    post<ClientView>(`/api/c/${token}/change-orders/${id}/approve`),
  clientDeclineChangeOrder: (token: string, id: string) =>
    post<ClientView>(`/api/c/${token}/change-orders/${id}/decline`),
};
