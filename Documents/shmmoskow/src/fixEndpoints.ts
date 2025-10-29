import { readFileSync, writeFileSync } from "fs";

const path = "data/article_urls.ids.json";
const arr = JSON.parse(readFileSync(path, "utf8"));

for (const row of arr) {
  if (row.id && !row.endpoint) {
    if (row.subtype === 'page') {
      row.endpoint = 'pages';
    } else {
      row.endpoint = 'posts';
    }
  }
}

writeFileSync(path, JSON.stringify(arr, null, 2), "utf8");
console.log("[DONE] Все endpoint проставлены.");



