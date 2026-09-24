import fs from "node:fs/promises";
import path from "node:path";
import { performance } from "node:perf_hooks";
import PptxGenJS from "pptxgenjs";

const outputDir = process.argv[2] || "/output";
const limits = Object.freeze({ chars: 200_000, sections: 100, rows: 1_000, cols: 12, slides: 250, bytes: 10_000_000 });
const ink = "233248", muted = "556579", accent = "296579";
const fontFace = "DejaVu Sans";

function validate(doc) {
  const raw = JSON.stringify(doc);
  if (raw.length > limits.chars || doc.sections.length > limits.sections) throw new Error("source limit exceeded");
  for (const table of doc.tables || []) {
    if (table.rows.length > limits.rows || table.headers.length > limits.cols ||
        table.rows.some(row => row.length !== table.headers.length)) throw new Error("table limit exceeded");
  }
  if ((doc.chart?.labels?.length || 0) > 40) throw new Error("chart limit exceeded");
}

function createDeck(doc) {
  validate(doc);
  const pptx = new PptxGenJS();
  pptx.layout = "LAYOUT_WIDE";
  pptx.author = "AI Research OS synthetic qualification";
  pptx.subject = "Synthetic report-bound presentation";
  pptx.lang = "uk-UA";
  pptx.theme = { headFontFace: fontFace, bodyFontFace: fontFace, lang: "uk-UA" };
  let count = 0;
  function slide(title, continuation = false) {
    if (++count > limits.slides) throw new Error("slide limit exceeded");
    const s = pptx.addSlide();
    s.background = { color: "FFFFFF" };
    s.addText(title + (continuation ? " (продовження)" : ""),
      { x: 0.75, y: 0.42, w: 11.8, h: 0.72, fontFace, fontSize: 28, bold: true, color: ink,
        margin: 0, breakLine: false });
    s.addText(`${doc.method} · ${doc.sourceId} · ${doc.version} · ${doc.status}`,
      { x: 0.75, y: 7.07, w: 11.8, h: 0.22, fontFace, fontSize: 9, color: muted, margin: 0 });
    return s;
  }
  function textPages(title, content) {
    // Character chunks preserve every input code point. Resource bounds fail closed.
    const chunks = content.match(/[\s\S]{1,850}/gu) || [""];
    chunks.forEach((chunk, i) => {
      const s = slide(title, i > 0);
      s.addText(chunk, { x: 0.8, y: 1.38, w: 11.7, h: 5.32, fontFace,
        fontSize: 17, color: ink, margin: 0, breakLine: false, valign: "top" });
    });
  }
  const title = slide(doc.title);
  title.addText(`Джерело: ${doc.sourceId}\nВерсія: ${doc.version}\nСтатус джерела: ${doc.status}`,
    { x: 0.8, y: 2.2, w: 11.5, h: 2, fontFace, fontSize: 22, color: accent, margin: 0 });
  if (doc.summary) textPages("Резюме", doc.summary);
  for (const section of doc.sections) {
    textPages(section.title, section.text);
    if (section.citations?.length) textPages("Посилання: " + section.title, section.citations.join("\n"));
  }
  for (const table of doc.tables || []) {
    const pageRows = 11;
    for (let start = 0; start < table.rows.length; start += pageRows) {
      const s = slide(table.title, start > 0);
      s.addTable([table.headers, ...table.rows.slice(start, start + pageRows)], {
        x: 0.8, y: 1.5, w: 11.7, h: 4.9, colW: 11.7 / table.headers.length,
        fontFace, fontSize: 13, color: ink, border: { type: "solid", pt: 0.4, color: "CAD3DC" },
        margin: 0.08, autoFit: false, valign: "mid", rowH: 0.35
      });
      s.addText(`База: ${table.base} · Одиниця: ${table.unit}`,
        { x: 0.8, y: 6.6, w: 11.7, h: 0.25, fontFace, fontSize: 11, color: muted, margin: 0 });
    }
  }
  if (doc.chart && doc.chart.supported === true &&
      doc.chart.labels?.length && doc.chart.labels.length === doc.chart.values?.length &&
      doc.chart.values.every(Number.isFinite) && doc.chart.base && doc.chart.unit) {
    const s = slide(doc.chart.title);
    s.addChart(pptx.ChartType.bar,
      [{ name: doc.chart.unit, labels: doc.chart.labels, values: doc.chart.values }],
      { x: 1, y: 1.55, w: 11, h: 4.85, catAxisLabelFontFace: fontFace,
        valAxisLabelFontFace: fontFace, showLegend: false, showValue: true, chartColors: [accent] });
    s.addText(`База: ${doc.chart.base} · Одиниця: ${doc.chart.unit}`,
      { x: 0.8, y: 6.55, w: 11.7, h: 0.3, fontFace, fontSize: 11, color: muted, margin: 0 });
  }
  if (doc.registry?.length) textPages("Реєстр джерел", doc.registry.join("\n"));
  if (doc.limitations?.length) textPages("Обмеження", doc.limitations.join("\n"));
  return { pptx, count };
}

const longText = "Довгий український текст дослідження зберігається без переказу. ".repeat(55);
const longUrl = "https://example.invalid/source/" + "long-path-".repeat(24);
const desk = {
  method: "DESK", sourceId: "synthetic-desk-report-1", version: "revision-3-review-synthetic",
  status: "Статус перевірки не підтверджено", title: "Огляд джерел і обмежень",
  summary: "Синтетичне резюме без дослідницьких висновків.",
  sections: [
    { title: "Контекст", text: longText, citations: ["CIT-01", longUrl] },
    { title: "Матеріали", text: "Збережений текст розділу. ".repeat(110), citations: ["CIT-02"] },
  ],
  registry: ["CIT-01: синтетичне джерело", `CIT-02: ${longUrl}`],
  limitations: ["Синтетичні дані не описують реальне дослідження."], tables: []
};
const quant = {
  method: "QUANTITATIVE", sourceId: "synthetic-composition-1", version: "composition-7",
  status: "Прийнято", title: "Кількісний звіт",
  summary: null,
  sections: [
    { title: "Метод", text: "База: синтетичні учасники. Одиниця: відсоток. " + longText },
    { title: "Збережені значення", text: "Група А: 42 %. Група Б: 58 %. Без нових обчислень." },
  ],
  tables: [{ title: "Підтверджена таблиця", headers: ["Група", "Значення", "Одиниця"],
    rows: Array.from({ length: 22 }, (_, i) => [i === 0 ? "Група А" : `Рядок ${i + 1}`, i === 0 ? "42" : String(i + 1), "%"]),
    base: "синтетичні учасники", unit: "%" }],
  chart: { supported: true, title: "Підтверджені значення", labels: ["Група А", "Група Б"],
    values: [42, 58], base: "синтетичні учасники", unit: "%" },
  limitations: ["Тільки синтетична демонстрація."]
};

if (process.argv.includes("--self-test-limits")) {
  let rejected = false;
  try { validate({ ...desk, sections: [{ title: "oversized", text: "X".repeat(210_000) }] }); }
  catch { rejected = true; }
  if (!rejected) throw new Error("oversized source accepted");
  rejected = false;
  try { validate({ ...quant, tables: [{ headers: ["x"], rows: Array.from({ length: 1001 }, () => ["x"]) }] }); }
  catch { rejected = true; }
  if (!rejected) throw new Error("oversized table accepted");
  const unsupported = createDeck({ ...quant, chart: { ...quant.chart, base: null } });
  if (unsupported.count !== 10) throw new Error("unsupported chart not omitted");
  process.stdout.write("resource_limits_ok unsupported_chart_omitted\n");
  process.exit(0);
}

await fs.mkdir(outputDir, { recursive: true });
for (const [name, doc] of [
  ["desk", desk],
  ["desk-draft", { ...desk, sourceId: "synthetic-desk-draft", version: "revision-1-review-none", status: "Чернетка" }],
  ["desk-approved", { ...desk, sourceId: "synthetic-desk-approved", version: "revision-2-review-approved", status: "Схвалено" }],
  ["quant", quant],
]) {
  const start = performance.now();
  const { pptx, count } = createDeck(doc);
  const file = path.join(outputDir, `${name}.pptx`);
  const temporary = `${file}.pending.pptx`;
  try {
    await pptx.writeFile({ fileName: temporary });
    if ((await fs.stat(temporary)).size > limits.bytes) throw new Error("compressed PPTX size exceeded");
    await fs.rename(temporary, file);
  } finally {
    await fs.rm(temporary, { force: true });
  }
  const size = (await fs.stat(file)).size;
  process.stdout.write(JSON.stringify({ name, slides: count, bytes: size,
    ms: Math.round(performance.now() - start), rss: process.memoryUsage().rss,
    node: process.version, pptxgenjs: "4.0.1" }) + "\n");
}
