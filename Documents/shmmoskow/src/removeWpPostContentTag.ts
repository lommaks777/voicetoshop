import "dotenv/config";
import axios from "axios";
import { readFileSync } from "fs";

const BASE = (process.env.WP_BASE_URL || "").replace(/\/$/, "");
const arr = JSON.parse(readFileSync("data/article_urls.ids.json", "utf8"));

function cleanWpPostContentMarkers(html: string): string {
  return html.replace(/<!--\s*\/wp:post-content\s*-->/gi, '');
}

async function processOne(id: number, endpoint: string) {
  try {
    const { data } = await axios.get(`${BASE}/wp-json/wp/v2/${endpoint}/${id}`);
    const orig = data.content?.rendered || '';
    const cleaned = cleanWpPostContentMarkers(orig);
    if (orig !== cleaned) {
      await axios.post(`${BASE}/wp-json/wp/v2/${endpoint}/${id}`, { content: cleaned });
      console.log(`[CLEANED] id=${id}`);
    } else {
      console.log(`[SKIP] id=${id} — тег не найден`);
    }
  } catch (e: any) {
    console.error(`[ERR] id=${id}:`, e.message || e);
  }
}

async function main() {
  const targets = arr.filter(r => r.id && r.endpoint);
  console.log(`[INFO] Найдено ${targets.length} статей для очистки`);
  for (const row of targets) {
    await processOne(row.id, row.endpoint);
    await new Promise(r => setTimeout(r, 150)); // легкий троттлинг
  }
  console.log("Готово!");
}

main();
