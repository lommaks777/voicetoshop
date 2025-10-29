import "dotenv/config";
import axios from "axios";
import { readFileSync, writeFileSync, mkdirSync } from "fs";
import { basename } from "path";

const BASE = (process.env.WP_BASE_URL || "").replace(/\/$/, "");
if (!BASE) {
  console.error("Set WP_BASE_URL in .env");
  process.exit(1);
}

const inputPath = process.argv[2];
if (!inputPath) {
  console.error("Usage: npm run resolve:ids -- <path-to-urls.txt>");
  process.exit(1);
}

const raw = readFileSync(inputPath, "utf8")
  .split(/\r?\n/)
  .map(s => s.trim())
  .filter(Boolean);

function toSlug(u: string) {
  try {
    const url = new URL(u);
    // берем последний непустой сегмент пути
    const parts = url.pathname.split("/").filter(Boolean);
    return parts[parts.length - 1] || "";
  } catch {
    // если это уже slug
    return u.replace(/^[\/]+|[\/]+$/g, "");
  }
}

async function byType(type: string, slug: string) {
  const { data } = await axios.get(`${BASE}/wp-json/wp/v2/${type}`, {
    params: { slug, _fields: "id,slug,link" }
  });
  return Array.isArray(data) ? data[0] : null;
}

async function bySearch(slug: string) {
  const { data } = await axios.get(`${BASE}/wp-json/wp/v2/search`, {
    params: { search: slug, per_page: 10, _fields: "id,subtype,url" }
  });
  if (!Array.isArray(data)) return null;

  // сначала точное совпадение по slug в url
  const exact = data.find((x: any) => typeof x.url === "string" && x.url.includes(`/${slug}/`));
  return exact || data[0] || null;
}

type Row = { url: string; slug: string; id: number | ""; subtype: string | ""; endpoint: string | "" };

async function resolveOne(url: string): Promise<Row> {
  const slug = toSlug(url);
  // 1) попробуем как пост
  let hit = await byType("posts", slug);
  if (hit) return { url, slug, id: hit.id, subtype: "post", endpoint: "posts" };

  // 2) как страница
  hit = await byType("pages", slug);
  if (hit) return { url, slug, id: hit.id, subtype: "page", endpoint: "pages" };

  // 3) общий поиск
  const s = await bySearch(slug);
  if (s && s.id && s.subtype) {
    return { url, slug, id: s.id, subtype: s.subtype, endpoint: `${s.subtype}s` };
  }

  return { url, slug, id: "", subtype: "", endpoint: "" };
}

async function main() {
  console.log(`[INFO] Resolving ${raw.length} urls against ${BASE}`);
  const out: Row[] = [];
  for (const u of raw) {
    try {
      const row = await resolveOne(u);
      out.push(row);
      const tag = row.id ? "OK" : "MISS";
      console.log(`[${tag}] ${u} -> id=${row.id} subtype=${row.subtype}`);
      // легкий троттлинг
      await new Promise(r => setTimeout(r, 120));
    } catch (e: any) {
      console.error(`[ERR] ${u}: ${e?.message || e}`);
      out.push({ url: u, slug: toSlug(u), id: "", subtype: "", endpoint: "" });
    }
  }

  mkdirSync("data", { recursive: true });
  const base = basename(inputPath).replace(/\.[^.]+$/, "");
  writeFileSync(`data/${base}.ids.json`, JSON.stringify(out, null, 2), "utf8");
  const csv = [
    "url,slug,id,subtype,endpoint",
    ...out.map(r => [r.url, r.slug, r.id, r.subtype, r.endpoint].join(","))
  ].join("\n");
  writeFileSync(`data/${base}.ids.csv`, csv, "utf8");

  console.log(`[DONE] Saved data/${base}.ids.json and data/${base}.ids.csv`);
}
main().catch(e => (console.error(e), process.exit(1)));








