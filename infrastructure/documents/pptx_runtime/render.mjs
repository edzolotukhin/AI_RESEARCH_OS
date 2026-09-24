import PptxGenJS from "pptxgenjs";
import JSZip from "jszip";

const FONT = "DejaVu Sans";
const LIMITS = { chars: 200_000, sections: 100, rows: 1_000, cols: 12,
  chartPoints: 40, slides: 250, zip: 10_000_000, raw: 20_000_000 };
const MEDIA = "application/vnd.openxmlformats-officedocument.presentationml.presentation";

function check(doc) {
  if (!["DESK", "QUANTITATIVE"].includes(doc.method) ||
      !doc.project_id || !doc.run_id || !doc.source_id || !doc.source_version || !doc.status)
    throw new Error("invalid source identity");
  if (JSON.stringify(doc).length > LIMITS.chars || doc.sections.length > LIMITS.sections)
    throw new Error("source resource limit");
  for (const table of doc.tables || []) {
    if (!table.headers.length || table.headers.length > LIMITS.cols ||
        table.rows.length > LIMITS.rows ||
        table.headers.some(value => String(value).length > 42) ||
        table.rows.some(row => row.length !== table.headers.length ||
          row.some(value => String(value).length > 42)))
      throw new Error("table resource limit");
  }
  for (const chart of doc.charts || []) {
    if (chart.labels.length > LIMITS.chartPoints || chart.labels.length !== chart.values.length)
      throw new Error("chart resource limit");
  }
}

function makePresentation(doc) {
  check(doc);
  const pptx = new PptxGenJS();
  pptx.layout = "LAYOUT_WIDE";
  pptx.author = "AI Research OS";
  pptx.lang = "uk-UA";
  pptx.theme = { headFontFace: FONT, bodyFontFace: FONT, lang: "uk-UA" };
  let slideCount = 0;
  function addSlide(title, continuation = false) {
    if (++slideCount > LIMITS.slides) throw new Error("slide resource limit");
    const slide = pptx.addSlide();
    slide.background = { color: "FFFFFF" };
    slide.addText(title + (continuation ? " (продовження)" : ""),
      { x: 0.75, y: 0.4, w: 11.85, h: 0.75, fontFace: FONT, fontSize: 28,
        bold: true, color: "233248", margin: 0, breakLine: false });
    slide.addText(`${doc.method} · ${doc.source_id} · ${doc.source_version} · ${doc.status}`,
      { x: 0.75, y: 7.07, w: 11.8, h: 0.22, fontFace: FONT,
        fontSize: 9, color: "556579", margin: 0 });
    return slide;
  }
  function textPages(title, value) {
    // Slice only at the layout layer; every character appears on a slide.
    const chunks = value.match(/[\s\S]{1,850}/gu) || [""];
    chunks.forEach((chunk, index) => {
      const slide = addSlide(title, index > 0);
      slide.addText(chunk, { x: 0.8, y: 1.35, w: 11.7, h: 5.35,
        fontFace: FONT, fontSize: 17, color: "233248", margin: 0, valign: "top" });
    });
  }
  const first = addSlide(doc.title.length <= 70 ? doc.title : "Презентація звіту");
  first.addText(`Джерело: ${doc.source_id}\nВерсія: ${doc.source_version}\nСтатус джерела: ${doc.status}`,
    { x: 0.8, y: 2.15, w: 11.5, h: 2.4, fontFace: FONT,
      fontSize: 20, color: "296579", margin: 0 });
  if (doc.title.length > 70) textPages("Повна назва звіту", doc.title);
  if (`${doc.source_id}${doc.source_version}${doc.status}`.length > 120)
    textPages("Ідентифікатори джерела",
      `Джерело: ${doc.source_id}\nВерсія: ${doc.source_version}\nСтатус джерела: ${doc.status}`);
  if (doc.summary) textPages("Резюме", doc.summary);
  for (const section of doc.sections) {
    const heading = section.title.length <= 70 ? section.title : "Розділ звіту";
    if (section.title.length > 70) textPages("Назва розділу", section.title);
    for (const paragraph of section.paragraphs) textPages(heading, paragraph);
    if (section.citations?.length) textPages(`Посилання: ${section.title}`, section.citations.join("\n"));
  }
  for (const table of doc.tables || []) {
    const heading = table.title.length <= 70 ? table.title : "Таблиця звіту";
    if (table.title.length > 70) textPages("Назва таблиці", table.title);
    for (let start = 0; start < Math.max(1, table.rows.length); start += 11) {
      const slide = addSlide(heading, start > 0);
      slide.addTable([table.headers, ...table.rows.slice(start, start + 11)], {
        x: 0.8, y: 1.5, w: 11.7, h: 4.9, colW: 11.7 / table.headers.length,
        fontFace: FONT, fontSize: 13, color: "233248", margin: 0.08,
        border: { type: "solid", pt: 0.4, color: "CAD3DC" }, rowH: 0.35 });
      const context = [table.base && `База: ${table.base}`, table.unit && `Одиниця: ${table.unit}`].filter(Boolean);
      if (context.length) slide.addText(context.join(" · "),
        { x: 0.8, y: 6.6, w: 11.7, h: 0.25, fontFace: FONT,
          fontSize: 11, color: "556579", margin: 0 });
    }
  }
  for (const chart of doc.charts || []) {
    if (!chart.supported || !chart.base || !chart.unit ||
        !chart.labels?.length || chart.labels.length !== chart.values?.length ||
        !chart.values.every(Number.isFinite)) continue;
    const heading = chart.title.length <= 70 ? chart.title : "Графік звіту";
    if (chart.title.length > 70) textPages("Назва графіка", chart.title);
    const slide = addSlide(heading);
    slide.addChart(pptx.ChartType.bar,
      [{ name: chart.unit, labels: chart.labels, values: chart.values }],
      { x: 1, y: 1.55, w: 11, h: 4.85, chartColors: ["296579"],
        showLegend: false, showValue: true, catAxisLabelFontFace: FONT,
        valAxisLabelFontFace: FONT });
    slide.addText(`База: ${chart.base} · Одиниця: ${chart.unit}`,
      { x: 0.8, y: 6.55, w: 11.7, h: 0.3, fontFace: FONT,
        fontSize: 11, color: "556579", margin: 0 });
  }
  if (doc.citation_registry?.length)
    textPages("Реєстр джерел", doc.citation_registry.map(([key, value]) => `${key}: ${value}`).join("\n"));
  if (doc.links?.length) textPages("Посилання", doc.links.join("\n"));
  if (doc.limitations?.length) textPages("Обмеження", doc.limitations.join("\n"));
  for (const notice of doc.unavailable || []) textPages("Недоступний матеріал", notice);
  return pptx;
}

async function validatePackage(buffer) {
  if (buffer.length > LIMITS.zip || !buffer.subarray(0, 4).equals(Buffer.from([0x50, 0x4b, 0x03, 0x04])))
    throw new Error("PPTX output limit");
  const zip = await JSZip.loadAsync(buffer);
  let uncompressed = 0;
  const paths = Object.keys(zip.files);
  if (!paths.includes("ppt/presentation.xml")) throw new Error("invalid OOXML package");
  for (const name of paths) {
    const file = zip.files[name];
    uncompressed += file._data?.uncompressedSize || 0;
    if (uncompressed > LIMITS.raw || /(?:vbaProject\.bin|\.(?:exe|dll|js))$/i.test(name))
      throw new Error("unsafe PPTX package");
    if (name.endsWith(".rels")) {
      const xml = await file.async("string");
      if (/TargetMode\s*=\s*["']External["']/i.test(xml))
        throw new Error("external OOXML relationship");
    }
  }
}

let input = "";
for await (const part of process.stdin) {
  input += part;
  if (input.length > LIMITS.chars * 4) throw new Error("input resource limit");
}
const doc = JSON.parse(input);
const output = await makePresentation(doc).write({ outputType: "nodebuffer" });
const buffer = Buffer.isBuffer(output) ? output : Buffer.from(output);
await validatePackage(buffer);
process.stdout.write(buffer);
