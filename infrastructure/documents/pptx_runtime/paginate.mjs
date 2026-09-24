// Conservative, source-preserving text pagination for the fixed 11.7 x 5.35 in body.
// The fallback keeps a 69-100-unit token on one slide at 12 pt; longer
// indivisible tokens fail closed rather than overflow or silently truncate.
const NORMAL_FONT = 17;
const TOKEN_FONT = 12;
const NORMAL_UNITS = 68;
const TOKEN_UNITS = 100;
const MAX_LINES = 14;
const MAX_CHARS = 700;
const BREAKABLE_SPACE = /[ \t\r\n]+/gu; // NBSP is deliberately indivisible.

function units(char) {
  const code = char.codePointAt(0);
  return (code >= 0x1100 && (
    code <= 0x11ff || code >= 0x2e80 && code <= 0xa4cf ||
    code >= 0xac00 && code <= 0xd7ff || code >= 0xf900 && code <= 0xfaff ||
    code >= 0x1f300)) ? 2 : 1;
}

function tokenWidth(text) {
  let largest = 0;
  for (const token of text.split(BREAKABLE_SPACE)) {
    let width = 0;
    for (const char of token) width += units(char);
    largest = Math.max(largest, width);
  }
  return largest;
}

function fontFor(text) {
  const width = tokenWidth(text);
  if (width > TOKEN_UNITS) throw new Error("indivisible PPTX token exceeds readable width");
  return width > NORMAL_UNITS ? TOKEN_FONT : NORMAL_FONT;
}

function fits(text) {
  const font = fontFor(text);
  const lineWidth = font === NORMAL_FONT ? NORMAL_UNITS : TOKEN_UNITS;
  if (text.length > MAX_CHARS) return false;
  let lines = 1;
  let column = 0;
  for (const char of text) {
    if (char === "\n" || char === "\r") {
      if (char === "\n") lines += 1;
      column = 0;
      continue;
    }
    const width = units(char);
    if (column + width > lineWidth) {
      lines += 1;
      column = 0;
    }
    column += width;
    if (lines > MAX_LINES) return false;
  }
  return true;
}

function boundaryPositions(text, expression) {
  return Array.from(text.matchAll(expression), match => match.index + match[0].length)
    .filter(position => position > 0 && position < text.length);
}

function latestFitting(text, positions) {
  for (let index = positions.length - 1; index >= 0; index--) {
    const position = positions[index];
    if (position <= MAX_CHARS && fits(text.slice(0, position))) return position;
  }
  return 0;
}

export function paginateText(value) {
  const text = String(value);
  fontFor(text);
  if (!text) return [{ text: "", fontSize: NORMAL_FONT }];
  const pages = [];
  let remaining = text;
  while (remaining) {
    if (fits(remaining)) {
      pages.push({ text: remaining, fontSize: fontFor(remaining) });
      break;
    }
    const words = latestFitting(remaining, boundaryPositions(remaining, /[ \t\r\n]+/gu));
    const sentences = latestFitting(remaining,
      boundaryPositions(remaining, /[.!?。！？]+[\])}"'»”’]*[ \t\r\n]+/gu));
    const paragraphs = latestFitting(remaining,
      boundaryPositions(remaining, /\n[ \t]*\n+/gu));
    const cut = paragraphs >= words / 2 ? paragraphs :
      sentences >= words / 2 ? sentences : words;
    if (!cut) throw new Error("PPTX text has no safe slide boundary");
    const chunk = remaining.slice(0, cut);
    if (!chunk.trim()) throw new Error("PPTX text would produce empty continuation");
    pages.push({ text: chunk, fontSize: fontFor(chunk) });
    remaining = remaining.slice(cut);
    if (!remaining.trim()) {
      const joined = pages[pages.length - 1].text + remaining;
      if (!fits(joined)) throw new Error("PPTX trailing whitespace exceeds safe area");
      pages[pages.length - 1] = { text: joined, fontSize: fontFor(joined) };
      break;
    }
  }
  return pages;
}
