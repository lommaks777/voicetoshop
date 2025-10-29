import 'dotenv/config';
import { getPost, updatePostContent } from './wordpress.js';
import { pickWidgetByContent } from './llm.js';
import { getWidgetHtmlById } from './placement.js';
import { insertWidgetHtml, countWidgets } from './html.js';
import fs from 'fs';

async function main() {
  const args = process.argv.slice(2);
  const postId = Number(args.find(a => !a.startsWith('--')));
  const dryRun = args.includes('--dry-run');
  if (!postId) {
    console.error('Укажите id поста: npm run run:one -- <id> [--dry-run]');
    process.exit(1);
  }

  const post = await getPost(postId);
  const widgets = JSON.parse(fs.readFileSync('widgets.json', 'utf-8'));
  const articleText = post.content?.rendered || '';

  // Проверяем лимит только по исходному контенту
  if (countWidgets(articleText) >= 2) {
    console.warn('В статье уже размещено 2 или более виджетов. Новые не будут вставлены.');
    if (dryRun) {
      console.log('--- Исходный контент ---\n', articleText.slice(0, 500), '...');
      console.log('--- Новый контент ---\n', articleText.slice(0, 500), '...');
      console.log('Контент не изменился.');
    }
    return;
  }

  // 1. Подбор webinar
  const webinarWidgets = widgets.filter((w: any) => w.type === 'webinar');
  const webinarResult = await pickWidgetByContent(articleText, webinarWidgets);
  const { embed_html: webinar_html } = getWidgetHtmlById(webinarResult.best_widget_id);

  // 2. Подбор lead_magnet
  const leadmagnetWidgets = widgets.filter((w: any) => w.type === 'lead_magnet');
  const leadmagnetResult = await pickWidgetByContent(articleText, leadmagnetWidgets);
  const { embed_html: leadmagnet_html } = getWidgetHtmlById(leadmagnetResult.best_widget_id);

  // 3. Сначала вставляем bottom (обычно lead_magnet), затем top (обычно webinar)
  let htmlWithBottom = articleText;
  let placementBottom = null;
  let finalHtml = articleText;
  let placementTop = null;

  // Вставка bottom
  if (leadmagnetResult.placement_strategy === 'bottom') {
    const res = insertWidgetHtml(articleText, leadmagnetResult.best_widget_id, leadmagnet_html, leadmagnetResult.cta_text, 'bottom');
    htmlWithBottom = res.html;
    placementBottom = res.placement;
  } else if (leadmagnetResult.placement_strategy === 'top') {
    const res = insertWidgetHtml(articleText, leadmagnetResult.best_widget_id, leadmagnet_html, leadmagnetResult.cta_text, 'top');
    htmlWithBottom = res.html;
    placementBottom = res.placement;
  }

  // Вставка top в результат предыдущего
  if (webinarResult.placement_strategy === 'top') {
    const res = insertWidgetHtml(htmlWithBottom, webinarResult.best_widget_id, webinar_html, webinarResult.cta_text, 'top');
    finalHtml = res.html;
    placementTop = res.placement;
  } else if (webinarResult.placement_strategy === 'bottom') {
    const res = insertWidgetHtml(htmlWithBottom, webinarResult.best_widget_id, webinar_html, webinarResult.cta_text, 'bottom');
    finalHtml = res.html;
    placementTop = res.placement;
  }

  // Вывод инфы о вставках
  if (placementTop)
    console.log(`Виджет webinar (${webinarResult.best_widget_id}) будет вставлен в <${placementTop.container}> (${webinarResult.placement_strategy})`);
  if (placementTop)
    console.log('Текстовая подводка к webinar:', webinarResult.cta_text);
  if (placementBottom)
    console.log(`Виджет lead_magnet (${leadmagnetResult.best_widget_id}) будет вставлен в <${placementBottom.container}> (${leadmagnetResult.placement_strategy})`);
  if (placementBottom)
    console.log('Текстовая подводка к lead_magnet:', leadmagnetResult.cta_text);

  if (dryRun) {
    console.log('--- Исходный контент ---\n', articleText.slice(0, 500), '...');
    console.log('--- Новый контент ---\n', finalHtml.slice(0, 500), '...');
    if (articleText === finalHtml) {
      console.log('Контент не изменился.');
    } else {
      console.log('Контент был бы обновлён (dry-run).');
    }
  } else {
    if (articleText === finalHtml) {
      console.log('Контент не изменился, обновление не требуется.');
    } else {
      await updatePostContent(postId, finalHtml);
      console.log('Контент успешно обновлён!');
    }
  }
}

main().catch(e => { console.error(e); process.exit(1); });
