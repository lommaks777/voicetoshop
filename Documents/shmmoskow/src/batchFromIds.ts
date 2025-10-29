import { readFileSync } from "fs";
import { execSync } from "child_process";

const arr = JSON.parse(readFileSync("data/article_urls.ids.json", "utf8"));
const ids = arr.filter(r => r.has_widget === false && r.id && r.endpoint).map(r => r.id);

console.log(`[INFO] Будет обработано ${ids.length} статей`);

for (const id of ids) {
  try {
    console.log(`\n[RUN] npm run run:one -- ${id}`);
    execSync(`npm run run:one -- ${id}`, { stdio: "inherit" });
  } catch (e: any) {
    console.error(`[ERR] id=${id}:`, e.message || e);
  }
}






