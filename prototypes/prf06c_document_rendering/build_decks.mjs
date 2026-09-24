// Synthetic, content-preserving slide layout test. No network or research API.
import fs from "node:fs/promises";
import path from "node:path";
import { performance } from "node:perf_hooks";
import { pathToFileURL } from "node:url";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const DIR = path.dirname(new URL(import.meta.url).pathname).replace(/^\/(\w:)/, "$1");
const RUN_NAME = process.env.PRF06C_RUN_NAME || "";
if (RUN_NAME && !/^[a-z0-9][a-z0-9-]{0,40}$/.test(RUN_NAME)) throw new Error("invalid prototype run name");
const OUT = RUN_NAME ? path.join(DIR, "runs", RUN_NAME, "output") : path.join(DIR, "output");
const SKILL_DIR = process.env.SKILL_DIR;
const PY = process.env.RUNTIME_PYTHON;
if (!SKILL_DIR || !PY) throw new Error("SKILL_DIR and RUNTIME_PYTHON are required");
const { finalizePresentation, applyPresentationChartFont } = await import(
  pathToFileURL(path.join(SKILL_DIR, "container_tools/artifact_tool_utils.mjs")).href
);
const FONT = "DejaVu Sans";
const NAVY = "#182c43";
const BLUE = "#275b86";
const GREY = "#53677b";

function textBox(slide, text, left, top, width, height, size, bold = false, color = NAVY) {
  const box = slide.shapes.add({
    geometry: "textbox", position: { left, top, width, height },
    fill: "none", line: { fill: "none", width: 0 },
  });
  box.text = String(text);
  box.text.style = { typeface: FONT, fontSize: size, bold, color, autoFit: "none" };
  return box;
}

function baseSlide(deck, title, subtitle = "") {
  const slide = deck.slides.add();
  slide.background.fill = "#ffffff";
  textBox(slide, title, 70, 48, 1140, 85, 34, true);
  if (subtitle) textBox(slide, subtitle, 72, 124, 1135, 42, 15, false, GREY);
  return slide;
}

function chunks(text, max = 430) {
  if (text.length > 100000) throw new Error("oversized synthetic section");
  const result = [];
  let rest = text;
  while (rest.length) {
    if (rest.length <= max) { result.push(rest); break; }
    let cut = rest.lastIndexOf(" ", max);
    if (cut < max / 2) cut = max;
    else cut += 1;
    result.push(rest.slice(0, cut));
    rest = rest.slice(cut);
  }
  return result;
}

function build(doc) {
  const deck = Presentation.create({ slideSize: { width: 1280, height: 720 } });
  const cover = baseSlide(deck, doc.title);
  textBox(cover, `${doc.project}\n${doc.method}\nЗвіт: ${doc.report_id}\n${doc.revision ?? doc.composition_id}\n${doc.source_status}\n${doc.generated_at}`, 75, 225, 1100, 340, 27);
  const summary = baseSlide(deck, "Резюме", `${doc.method} · ${doc.report_id}`);
  textBox(summary, doc.summary, 75, 190, 1110, 390, 24);
  for (const section of doc.sections) {
    const parts = chunks(section.text);
    parts.forEach((part, index) => {
      const title = index ? `${section.title} (продовження ${index + 1})` : section.title;
      const slide = baseSlide(deck, title, `${doc.method} · ${doc.report_id}`);
      textBox(slide, part, 75, 185, 1120, 410, 20);
      if (index === parts.length - 1 && section.citations.length)
        textBox(slide, `Джерела: ${section.citations.join(", ")}`, 75, 626, 1110, 40, 15, false, BLUE);
    });
  }
  for (const table of doc.tables) {
    const perSlide = 8;
    for (let offset = 0; offset < table.rows.length; offset += perSlide) {
      const slide = baseSlide(deck, table.title + (offset ? " (продовження)" : ""), table.qualification);
      const values = [table.headers, ...table.rows.slice(offset, offset + perSlide)];
      const nativeTable = slide.tables.add({ rows: values.length, columns: table.headers.length, left: 75, top: 190,
                                             width: 1120, height: Math.min(390, values.length * 42), values });
      for (let row = 0; row < values.length; row++) {
        for (let column = 0; column < table.headers.length; column++) {
          nativeTable.getCell(row, column).text.style = { typeface: FONT, fontSize: 17,
                                                       color: NAVY, bold: row === 0 };
        }
      }
      textBox(slide, `Джерело: ${table.source_ref}`, 75, 630, 1100, 35, 15, false, BLUE);
    }
  }
  for (const chart of doc.charts) {
    if (!chart.render_chart) continue;
    const slide = baseSlide(deck, chart.title, `База: ${chart.base} · Одиниця: ${chart.unit}`);
    const native = slide.charts.add("bar", {
      position: { left: 120, top: 185, width: 1000, height: 390 },
      categories: chart.categories,
      series: [{ name: chart.unit, values: chart.values, fill: BLUE }],
      barOptions: { direction: "column", grouping: "clustered" },
      hasLegend: false, dataLabels: { showValue: true, position: "outEnd" },
    });
    applyPresentationChartFont(native, { fontFamily: FONT });
    textBox(slide, `Джерело: ${chart.source_ref}`, 75, 628, 1100, 40, 15, false, BLUE);
  }
  const limits = baseSlide(deck, "Обмеження", `${doc.method} · ${doc.report_id}`);
  textBox(limits, doc.limitations.join("\n\n"), 75, 185, 1110, 395, 22);
  const refs = baseSlide(deck, "Джерела", `${doc.method} · ${doc.report_id}`);
  textBox(refs, doc.sources.map(s => `${s.id}: ${s.title}\n${s.url}`).join("\n\n"), 75, 185, 1110, 410, 17);
  return deck;
}

await fs.mkdir(OUT, { recursive: true });
const metrics = {};
for (const name of ["desk", "quantitative"]) {
  const doc = JSON.parse(await fs.readFile(path.join(OUT, `${name}.json`), "utf8"));
  const start = performance.now();
  const deck = build(doc);
  const candidatePath = path.join(OUT, `${name}-candidate.pptx`);
  const finalPath = path.join(OUT, `${name}.pptx`);
  const validationDir = RUN_NAME ? path.join(DIR, "runs", RUN_NAME, "validation") : path.join(DIR, ".validation");
  await fs.mkdir(validationDir, { recursive: true });
  await (await PresentationFile.exportPptx(deck)).save(candidatePath);
  let finalization = "not_run";
  try {
    await finalizePresentation({
      workspaceDir: DIR, candidatePath, finalPath, pythonExecutable: PY,
      integrityValidatorPath: path.join(SKILL_DIR, "container_tools/inspect_presentation_package_integrity.py"),
      layoutValidatorPath: path.join(SKILL_DIR, "container_tools/inspect_presentation_layout_geometry.py"),
      layoutArgs: ["--expected-slide-size-emu", "12192000,6858000"],
      requiredNativeTableOwnerSlides: [],
      fontPolicy: { basis: "design", families: [FONT] },
      verifyArtifactToolImport: true,
      materializeLiteralChartWorkbooks: true,
      receiptPath: path.join(validationDir, `${name}.validation.json`),
    });
    finalization = "passed";
  } catch (error) {
    finalization = `failed: ${error.message}`;
  }
  const inspect = await deck.inspect({ kind: "slide,textbox,table,chart", maxChars: 100000 });
  await fs.writeFile(path.join(OUT, `${name}.inspect.ndjson`), inspect.ndjson);
  // This preview is exported from the in-memory deck, not from saved PPTX bytes.
  for (const index of [0, Math.min(2, deck.slides.items.length - 1), deck.slides.items.length - 1]) {
    const slide = deck.slides.items[index];
    const image = await deck.export({ slide, format: "png", scale: 1 });
    await fs.writeFile(path.join(OUT, `${name}-slide-${index + 1}.png`), new Uint8Array(await image.arrayBuffer()));
  }
  const stat = await fs.stat(finalization === "passed" ? finalPath : candidatePath);
  metrics[name] = { seconds: Math.round((performance.now() - start) / 1000 * 100) / 100,
                    slides: deck.slides.items.length, bytes: stat.size, finalization };
}
await fs.writeFile(path.join(OUT, "pptx_metrics.json"), JSON.stringify(metrics, null, 2));
process.stdout.write(JSON.stringify(metrics) + "\n");
