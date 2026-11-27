// What crosses into the page from TaoChronos's chat runtime: its answers — the shapes src/taochronos/chat writes,
// the same module in the browser's worker and under `taochronos serve` — and the messages between runtime.js,
// worker.js and unpack-worker.js.  Read by the type checker only (README.md): it is kept out of web/, which the site
// copies as it is, and no browser loads it.  It imports nothing of the page's, so that worker code importing it brings
// no page code into the module workers' program (tsconfig.worker.json); what runtime.js offers the page (Runtime, the
// options of a call) is typed in runtime.js.  A field the Python renames is renamed here, and tsc then names every
// place the page still reads the old one.

// ------------------------------------------------------------------ the runtime's answers (src/taochronos/chat)

/** ChatRuntime.info() (chat/__init__.py); worker.js's init adds load_ms and version_manifest. */
export interface RuntimeInfo {
  name: string;
  version: string;
  runtime: "browser" | "server";
  profile: string;
  corpus: CorpusInfo;
  tools: { offered: number; families: Families };
  assistant_name: string;
  agent_name: string;
  publisher: string;
  engine_model: string | null;
  code_mode: boolean;
  starters: { title: string; prompt: string }[];
  mydata: { accepted: string[]; max_bytes: number; max_datasets: number; prescriptions: boolean };
  system_prompt: string;
  load_ms?: number;
  version_manifest?: string;
  /** in the browser (worker.js): what searches run on, as Python found it (taocore.status()) */
  taocore?: TaoCoreStatus;
}

/** TaoCore's state (src/taochronos/plugins/retrieval/taocore.py status()): the kernel in use, or none and why; how often
 * each way ran.  Without the module the worker says only why: {kernel: null, reason}. */
export interface TaoCoreStatus {
  kernel: "wasm" | "native" | null;
  reason: string;
  mode?: "auto" | "off" | "require" | "shadow";
  bm25?: number;
  dense?: number;
  grams?: number;
  python?: number;
  failed?: number;
  differed?: number;
}

/** CORPUS_LABELS' keys (chat/__init__.py): the demonstration corpus, the 要籍语料, the full corpus. */
export type CorpusKind = "demo" | "canon" | "full";

export interface CorpusInfo {
  books: number;
  passages: number;
  characters: number;
  by_period: Record<string, number>;
  large: boolean;
  demo: boolean;
  kind: CorpusKind;
  label: string;
  canon: { listed: number; held: number };
}

/** family_counts (chat/catalog.py): each family's FAMILIES entry, and how many of its tools are offered. */
export type Families = Record<string, { count: number; [meta: string]: unknown }>;

/** tool_entry, ENGINE_TOOLS, META_TOOLS (chat/catalog.py): a tool in neutral form, which llm/*.js put in their
 * provider's wire format. */
export interface ToolDef {
  name: string;
  tool: string;
  family: string;
  description: string;
  parameters: { type: "object"; properties: Record<string, unknown>; required?: string[] };
  expensive?: boolean;
}

export type CatalogMode = "core" | "all";

/** ChatRuntime.catalog(mode); `mydata`: the 我的资料 tools, apart, in core mode. */
export interface Catalog {
  mode: CatalogMode;
  tools: ToolDef[];
  families: Families;
  mydata?: ToolDef[];
}

/** runtime/boot.json (src/taochronos/chat/build.py): what the browser's runtime will answer once loaded. */
export interface BootFile {
  info?: RuntimeInfo;
  catalogs?: Partial<Record<CatalogMode, Catalog>>;
}

/** citations() (chat/results.py): a passage a result names, CARD_FIELDS and its text as far as the result says. */
export interface CitationCard {
  passage_id: string;
  book_id?: string;
  title?: string;
  authors?: string[];
  dynasty?: string;
  year?: number;
  period?: string;
  locator?: string;
  labels?: string[];
  text?: string;
}

/** The kernel's receipt of a call, as shape() passes it on. */
export interface Receipt {
  tool?: string;
  version?: string;
  actor?: string;
  principal?: string;
  arguments_sha256?: string;
  result_sha256?: string;
  ok?: boolean;
  quarantined?: boolean;
  duration_ms?: number;
}

interface OutcomeBase {
  tool: string;
  duration_ms: number;
  text: string;
  summary: string;
  citations: CitationCard[];
  repaired?: string[];
  via?: "taochronos_call";
}

/** shape() (chat/__init__.py): a call's outcome, never an exception.  `result`: the tool's own value, whatever its
 * shape. */
export type ToolOutcome =
  | (OutcomeBase & { ok: true; result: unknown; receipt: Receipt })
  | (OutcomeBase & { ok: false; error: string });

/** ChatRuntime.passage(): a passage in full (classics.get_passage's fields, or a row of the user's data), or why
 * not. */
export type PassageView =
  | ({ ok: true; passage_id: string; text: string; prev?: string; next?: string }
      & Omit<CitationCard, "passage_id" | "text"> & Record<string, unknown>)
  | { ok: false; passage_id: string; error: string };

/** A dataset's summary (plugins/userdata/store.py Dataset.summary). */
export interface DatasetSummary { id: string; name: string; [field: string]: unknown }
/** ChatRuntime.data_add; `kept`: worker.js kept it for the next visit (IndexedDB). */
export type DataAddResult = { ok: true; dataset: DatasetSummary; kept?: boolean } | { ok: false; error: string };
export interface DataList {
  datasets: DatasetSummary[];
  limits: { bytes: number; datasets: number; accepted: string[] };
}
export type DataRemoveResult = { ok: true; removed: string; name: string } | { ok: false; error: string };
export type DataClearResult = { ok: true; removed: number };

/** RESEARCH_FIELDS (chat/__init__.py): what taochronos_research takes. */
export interface ResearchArgs {
  question: string;
  focus_terms?: string[];
  tracks?: string[];
  max_rounds?: number;
  forbidden_assumptions?: string[];
  holdout_after?: number;
  books?: string[];
}

/** ChatRuntime.session_view's `what`. */
export type SessionWhat = "summary" | "report" | "hypothesis" | "evidence";

/** A research run's states (chat/jobs.py: UNFINISHED, ENDED, interrupted), and "unknown": a run the server does not
 * know. */
export type JobState =
  | "queued" | "running" | "cancel_requested"
  | "completed" | "failed" | "cancelled"
  | "interrupted" | "unknown";

/** Jobs.view() (chat/jobs.py): GET /api/research/<job>.  `status`: the words of an earlier server (LEGACY). */
export interface JobView {
  id: string;
  state: JobState;
  status: string;
  question?: string;
  position?: number | null;
  queued_s?: number;
  run_s?: number;
  elapsed_s?: number;
  heartbeat_s?: number | null;
  progress_s?: number | null;
  progress?: { round?: number; hypotheses?: number; claims?: number } | null;
  session?: string | null;
  outcome?: ToolOutcome;
}

// ------------------------------------------------------------------ runtime.js <-> worker.js (postMessage)

/** The params of each method the page sends the worker: init, then what BOOT's _rpc answers (worker.js), data_add,
 * data_remove and data_clear by way of the worker's own IndexedDB. */
export interface WorkerParams {
  init: { base: string };
  info: undefined;
  catalog: { mode: CatalogMode };
  call: { name: string; arguments: object; max_chars?: number };
  passage: { id: string };
  session: { session_id: string; what: SessionWhat; hypothesis?: string; section?: string };
  data_add: { name: string; bytes: ArrayBuffer };
  data_list: undefined;
  data_remove: { id: string };
  data_clear: undefined;
}

/** What each method answers. */
export interface WorkerResults {
  init: RuntimeInfo;
  info: RuntimeInfo;
  catalog: Catalog;
  call: ToolOutcome;
  passage: PassageView;
  session: Record<string, unknown>;
  data_add: DataAddResult;
  data_list: DataList;
  data_remove: DataRemoveResult;
  data_clear: DataClearResult;
}

export type WorkerMethod = keyof WorkerParams;

/** page -> worker: {id, method, params} */
export type WorkerRequest = { [M in WorkerMethod]: { id: number; method: M; params: WorkerParams[M] } }[WorkerMethod];

/** worker -> page: a call's end, {id, result} or {id, error} */
export type WorkerReply =
  | { type?: undefined; id: number; result: unknown; error?: undefined }
  | { type?: undefined; id: number; error: string; result?: undefined };

/** worker -> page: the rest of the corpus indexed, a slice at a time, then kept (or not) */
export interface IndexEvent {
  type: "index";
  indexed?: number;
  total?: number;
  done?: boolean;
  kept?: boolean;
  error?: string;
}

/** worker -> page: what it says unasked — how its start goes, the index, the flag that interrupts Python */
export type WorkerEvent =
  | { type: "progress"; progress: number; message: string }
  | IndexEvent
  | { type: "interrupt"; buffer: SharedArrayBuffer };

export type WorkerMessage = WorkerReply | WorkerEvent;

// ------------------------------------------------------------------ worker.js <-> unpack-worker.js

export interface UnpackRequest { url: string; size: number }
/** One shape, read field by field (worker.js unpackCorpus): {got}, {unpacked} as it goes, then {unpacked, buffer}
 * or {error}. */
export interface UnpackMessage { got?: number; unpacked?: number; buffer?: ArrayBuffer; error?: string }
