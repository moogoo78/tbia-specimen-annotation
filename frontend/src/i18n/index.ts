import i18n from "i18next";
import { initReactI18next } from "react-i18next";

const en = {
  app: { title: "TBIA Specimen Annotation Platform", short: "TBIA Annotate" },
  nav: { explore: "Explore", institutions: "Institutions", dashboard: "Dashboard", login: "Sign in", logout: "Sign out" },
  inst: { title: "Collection institutions", datasets: "datasets", records: "records", viewAll: "View all records" },
  search: {
    placeholder: "Search taxon, locality, collector, catalog #…",
    results: "results", of: "of", clear: "clear", filters: "FILTERS",
  },
  facet: {
    source: "Collection institution", institutions: "Institution", aggregators: "Aggregator",
    completeness: "Data completeness", bio_group: "Biological group", kingdom_c: "Kingdom",
    county: "County", taxon_rank: "Taxon rank", basis_of_record: "Basis of record",
    type_status: "Type status", dataset_name: "Holding institution", collector: "Collector",
    record_number: "Record number",
    missing_coordinates: "Missing coordinates", missing_date: "Missing date",
    missing_identification: "Missing identification", has_media: "Has images",
  },
  collector: {
    search: "Search collector…", none: "No matching collectors",
    filterBy: "Show all {{n}} records by this collector",
  },
  view: { table: "Table", grid: "Grid", split: "Split", map: "Map" },
  col: {
    catalog: "Catalog #", record_number: "Record #", sciname: "Scientific name", common: "Common", family: "Family",
    group: "Group", county: "County", locality: "Locality", date: "Collected",
    institution: "Institution", completeness: "Completeness", gaps: "Gaps",
  },
  detail: {
    taxonomy: "Taxonomy", event: "Collection event", record: "Record metadata",
    media: "Media", annotations: "Annotations", missing: "missing",
    collector: "Collector", coordinates: "Coordinates", elevation: "Elevation",
    backToResults: "Back to results", noMedia: "No images for this specimen",
  },
  annotate: {
    title: "Fill the gaps", field: "Field", proposed: "Proposed value",
    note: "Note (optional)", submit: "Submit annotation", saveDraft: "Save draft",
    aiExtract: "AI extract from image", aiHint: "Review the AI draft, then edit and submit.",
    confidence: "confidence", accept: "Accept", reject: "Reject", merge: "Mark merged",
    loginToAnnotate: "Sign in to annotate", history: "Annotation history",
    apply: "Use", model: "Model",
  },
  status: {
    draft: "Draft", submitted: "Submitted", accepted: "Accepted",
    rejected: "Rejected", merged: "Merged",
  },
  dash: {
    title: "Contributions & feedback loop", byStatus: "By status", byInstitution: "By institution",
    institution: "Institution", records: "Records", identified: "Identified",
    georeferenced: "Georeferenced", dated: "Dated", media: "Media",
    completeness: "Avg completeness", export: "Export deltas", exported: "deltas ready to return",
    pending: "Pending review", mine: "My annotations", all: "All annotations",
  },
  login: { title: "Sign in", email: "Email", password: "Password", submit: "Sign in", demo: "Demo accounts" },
  fields: {
    scientificName: "Scientific name", eventDate: "Event date",
    decimalLatitude: "Latitude", decimalLongitude: "Longitude", locality: "Locality",
    taxonRank: "Taxon rank",
  },
};

const zh: typeof en = {
  app: { title: "TBIA 標本資料補遺平台", short: "TBIA 補遺" },
  nav: { explore: "探索", institutions: "典藏機構", dashboard: "貢獻儀表板", login: "登入", logout: "登出" },
  inst: { title: "典藏機構", datasets: "個資料集", records: "筆紀錄", viewAll: "查看全部紀錄" },
  search: {
    placeholder: "搜尋物種、地點、採集者、館號…",
    results: "筆結果", of: "／", clear: "清除", filters: "篩選條件",
  },
  facet: {
    source: "典藏機構", institutions: "典藏機構", aggregators: "整合平台",
    completeness: "資料完整度", bio_group: "生物分類群", kingdom_c: "界",
    county: "縣市", taxon_rank: "分類階層", basis_of_record: "紀錄類型",
    type_status: "模式標本", dataset_name: "資料集", collector: "採集者",
    record_number: "採集號",
    missing_coordinates: "缺少座標", missing_date: "缺少日期",
    missing_identification: "缺少鑑定", has_media: "具有影像",
  },
  collector: {
    search: "搜尋採集者…", none: "查無符合的採集者",
    filterBy: "顯示此採集者的全部 {{n}} 筆紀錄",
  },
  view: { table: "表格", grid: "圖卡", split: "分割", map: "地圖" },
  col: {
    catalog: "館號", record_number: "採集號", sciname: "學名", common: "俗名", family: "科",
    group: "類群", county: "縣市", locality: "地點", date: "採集日期",
    institution: "機構", completeness: "完整度", gaps: "缺漏",
  },
  detail: {
    taxonomy: "分類", event: "採集事件", record: "紀錄資訊",
    media: "影像", annotations: "標註", missing: "缺漏",
    collector: "採集者", coordinates: "座標", elevation: "海拔",
    backToResults: "返回結果", noMedia: "此標本沒有影像",
  },
  annotate: {
    title: "補齊缺漏資料", field: "欄位", proposed: "建議值",
    note: "備註（選填）", submit: "送出標註", saveDraft: "儲存草稿",
    aiExtract: "以 AI 辨識影像", aiHint: "檢視 AI 草稿，編輯後送出。",
    confidence: "信心值", accept: "採納", reject: "退回", merge: "標記為已合併",
    loginToAnnotate: "登入後即可標註", history: "標註紀錄",
    apply: "套用", model: "模型",
  },
  status: {
    draft: "草稿", submitted: "已送出", accepted: "已採納",
    rejected: "已退回", merged: "已合併",
  },
  dash: {
    title: "貢獻與回饋循環", byStatus: "依狀態", byInstitution: "依機構",
    institution: "機構", records: "紀錄數", identified: "已鑑定",
    georeferenced: "有座標", dated: "有日期", media: "有影像",
    completeness: "平均完整度", export: "匯出補遺", exported: "筆補遺可回饋",
    pending: "待審核", mine: "我的標註", all: "所有標註",
  },
  login: { title: "登入", email: "電子郵件", password: "密碼", submit: "登入", demo: "示範帳號" },
  fields: {
    scientificName: "學名", eventDate: "採集日期",
    decimalLatitude: "緯度", decimalLongitude: "經度", locality: "地點",
    taxonRank: "分類階層",
  },
};

i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, zh: { translation: zh } },
  lng: localStorage.getItem("tbia_lang") || "zh",
  fallbackLng: "en",
  interpolation: { escapeValue: false },
});

export default i18n;
