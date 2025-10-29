import "dotenv/config";
import axios from "axios";
import { readFileSync, writeFileSync } from "fs";

const BASE = (process.env.WP_BASE_URL || "").replace(/\/$/, "");
const path = "data/article_urls.ids.json";
const arr = JSON.parse(readFileSync(path, "utf8"));

function hasWidgetMarker(html: string): boolean {
  // Проверяем наличие маркера <!-- ai-cta:start id=... -->
  return /<!--\s*ai-cta:start id=\w+/i.test(html);
}

async function hasWidget(id: number, endpoint: string) {
  if (!id || !endpoint) return false;
  try {
    const { data } = await axios.get(`${BASE}/wp-json/wp/v2/${endpoint}/${id}`);
    return typeof data.content?.rendered === "string" && hasWidgetMarker(data.content.rendered);
  } catch {
    return false;
  }
}

async function main() {
  for (const row of arr) {
    if (row.id && row.endpoint) {
      row.has_widget = await hasWidget(row.id, row.endpoint);
      console.log(`[${row.has_widget ? "YES" : "NO"}] ${row.url}`);
    } else {
      row.has_widget = false;
    }
  }
  writeFileSync(path, JSON.stringify(arr, null, 2), "utf8");
  console.log("Готово! Файл обновлён.");
}

main();
