// Local experiment: import the SAVED PPTX and render selected slides with Artifact Tool.
// This does not prove PowerPoint/LibreOffice fidelity; no external service is used.
import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
import { performance } from "node:perf_hooks";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const DIR = path.dirname(new URL(import.meta.url).pathname).replace(/^\/(\w:)/, "$1");
const RUN_NAME = process.env.PRF06C_RUN_NAME || "";
if (RUN_NAME && !/^[a-z0-9][a-z0-9-]{0,40}$/.test(RUN_NAME)) throw new Error("invalid prototype run name");
const OUT = RUN_NAME ? path.join(DIR, "runs", RUN_NAME, "output") : path.join(DIR, "output");
const manifest = {};
for (const name of ["desk", "quantitative"]) {
  const pptx = path.join(OUT, `${name}.pptx`);
  const bytes = await fs.readFile(pptx);
  if (bytes.length > 5_000_000) throw new Error("prototype PPTX size budget exceeded");
  const checksum = crypto.createHash("sha256").update(bytes).digest("hex");
  const started = performance.now();
  const deck = await PresentationFile.importPptx(await FileBlob.load(pptx));
  const count = deck.slides.items.length;
  const indices = name === "desk" ? [0, 2, 8, count - 1] : [0, 2, 14, 18, count - 1];
  const assets = [];
  for (const index of indices) {
    if (index >= count) throw new Error("saved deck has fewer slides than expected");
    const slide = deck.slides.items[index];
    const image = await deck.export({ slide, format: "png", scale: 1 });
    const filename = `${name}-saved-${checksum.slice(0, 12)}-slide-${index + 1}.png`;
    const output = new Uint8Array(await image.arrayBuffer());
    if (output.length > 2_000_000) throw new Error("preview image size budget exceeded");
    await fs.writeFile(path.join(OUT, filename), output);
    assets.push({ slide: index + 1, filename, bytes: output.length });
  }
  manifest[name] = { source_sha256: checksum, slide_count: count,
                     renderer: "artifact-tool-imported-pptx-not-office-suite",
                     seconds: Math.round((performance.now() - started) / 10) / 100,
                     assets };
}
await fs.writeFile(path.join(OUT, "saved_preview_manifest.json"), JSON.stringify(manifest, null, 2));
process.stdout.write(JSON.stringify(manifest) + "\n");
