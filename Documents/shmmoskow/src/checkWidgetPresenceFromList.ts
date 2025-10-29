import { readFileSync, writeFileSync } from "fs";
import axios from "axios";

const inputPath = "data/url_list.txt";
const outPath = "data/widget_presence_from_list.json";
const raw = readFileSync(inputPath, "utf8").split(/\r?\n/).map(s => s.trim()).filter(Boolean);

const WIDGET_PATTERN = "https://shkolamasterov.online/pl/lite/widget";

async function checkUrl(url: string) {
  try {
    const { data } = await axios.get(url, { timeout: 10000 });
    return typeof data === "string" && data.includes(WIDGET_PATTERN);
  } catch (e) {
    console.error(`[ERR] ${url}:`, e.message || e);
    return false;
  }
}

async function main() {
  const results: { url: string; has_widget: boolean }[] = [];
  for (const url of raw) {
    const has = await checkUrl(url);
    results.push({ url, has_widget: has });
    console.log(`[${has ? "YES" : "NO"}] ${url}`);
    await new Promise(r => setTimeout(r, 300)); // throttle
  }
  writeFileSync(outPath, JSON.stringify(results, null, 2), "utf8");
  console.log(`Готово! Сохранено в ${outPath}`);
}

main();



