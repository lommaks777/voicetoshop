import 'dotenv/config';
import { listPosts, getPost, updatePostContent } from './wordpress.js';
import { pickWidgetByContent } from './llm.js';
import { getWidgetHtmlById } from './placement.js';
import { insertWidgetHtml } from './html.js';
import { loadState, saveState } from './state.js';
import fs from 'fs';

function parseArgs() {
  const args = process.argv.slice(2);
  return {
    dryRun: args.includes('--dry-run'),
    limit: Number((args.find(a => a.startsWith('--limit=')) || '').split('=')[1]) || 20,
    par: Number((args.find(a => a.startsWith('--par=')) || '').split('=')[1]) || 3,
  };
}

async function processPost(postId: number, widgets: any[], dryRun: boolean) {
  const post = await getPost(postId);
  const articleText = post.content?.rendered || '';
  const llmResult = await pickWidgetByContent(articleText, widgets);
  const { embed_html } = getWidgetHtmlById(llmResult.best_widget_id);
  const newHtml = insertWidgetHtml(articleText, llmResult.best_widget_id, embed_html, llmResult.placement_strategy);
  if (articleText === newHtml) {
    return { postId, changed: false };
  }
  if (!dryRun) {
    await updatePostContent(postId, newHtml);
  }
  return { postId, changed: true };
}

async function main() {
  const { dryRun, limit, par } = parseArgs();
  const widgets = JSON.parse(fs.readFileSync('widgets.json', 'utf-8'));
  const state = loadState();
  const processed: Set<number> = new Set(state.processed || []);

  let page = 1;
  let totalProcessed = 0;
  let stop = false;

  while (!stop && totalProcessed < 600) {
    const posts = await listPosts({ per_page: limit, page });
    if (!posts.length) break;
    const toProcess = posts.filter((p: any) => !processed.has(p.id)).slice(0, limit);
    if (!toProcess.length) break;

    const batches = [];
    for (let i = 0; i < toProcess.length; i += par) {
      batches.push(toProcess.slice(i, i + par));
    }
    for (const batch of batches) {
      await Promise.all(batch.map(async (post: any) => {
        try {
          const res = await processPost(post.id, widgets, dryRun);
          if (res.changed) {
            console.log(`[${post.id}] Обновлено!`);
          } else {
            console.log(`[${post.id}] Без изменений.`);
          }
          processed.add(post.id);
        } catch (e) {
          console.error(`[${post.id}] Ошибка:`, e.message);
        }
      }));
      totalProcessed += batch.length;
      if (totalProcessed >= 600) { stop = true; break; }
    }
    page++;
    saveState({ processed: Array.from(processed) });
  }
  saveState({ processed: Array.from(processed) });
  console.log('Готово. Всего обработано:', processed.size);
}

main().catch(e => { console.error(e); process.exit(1); });
