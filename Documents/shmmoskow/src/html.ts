import * as cheerio from 'cheerio';

export interface InsertResult {
  html: string;
  placement: {
    container: 'article' | 'body' | 'root';
    position: 'top' | 'bottom';
    method: 'prepend' | 'append' | 'afterFirstP';
  } | null;
}

function removeContactFormShortcodesAndForms(html: string): string {
  // Удаляем шорткоды
  let result = html.replace(/\[contact-form-7[^\]]*\]/gi, '');
  // Удаляем сгенерированные формы Contact Form 7
  const $ = cheerio.load(result, { decodeEntities: false });
  $('.wpcf7').remove();
  return $.root().html() || '';
}

/**
 * Проверяет количество уже вставленных виджетов по наличию 'shkolamasterov.online/pl/lite/widget'
 */
export function countWidgets(html: string): number {
  return (html.match(/shkolamasterov\.online\/pl\/lite\/widget/gi) || []).length;
}

function cleanWpPostContentMarkers(html: string): string {
  // Удаляем все <!-- /wp:post-content -->
  return html.replace(/<!--\s*\/wp:post-content\s*-->/gi, '');
}

/**
 * Вставляет HTML-виджет с маркером <!-- ai-cta:start id=... --> и cta_text в статью
 * @param html HTML статьи
 * @param widgetId id виджета
 * @param widgetHtml HTML виджета
 * @param ctaText текстовая подводка
 * @param position 'top' | 'bottom'
 * @returns { html, placement }
 */
export function insertWidgetHtml(
  html: string,
  widgetId: string,
  widgetHtml: string,
  ctaText: string,
  position: 'top' | 'bottom' = 'top'
): InsertResult {
  html = removeContactFormShortcodesAndForms(html);
  html = cleanWpPostContentMarkers(html);
  const $ = cheerio.load(html, { decodeEntities: false });
  const marker = `<!-- ai-cta:start id=${widgetId} -->`;
  // Удаляем /wp:post-content из вставляемого блока на всякий случай
  const block = `${marker}\n<p class=\"ai-cta-text\">${ctaText}</p>\n${widgetHtml}\n<!-- ai-cta:end -->`.replace(/<!--\s*\/wp:post-content\s*-->/gi, '');
  let container: 'article' | 'body' | 'root' = 'root';
  let method: 'prepend' | 'append' | 'afterFirstP' = 'prepend';

  if (position === 'top') {
    // Вставка после первого <p> внутри <article> или <body>
    let target = null;
    if ($('article').length && $('article p').length) {
      target = $('article p').first();
      target.after('\n' + block + '\n');
      container = 'article';
      method = 'afterFirstP';
    } else if ($('body').length && $('body p').length) {
      target = $('body p').first();
      target.after('\n' + block + '\n');
      container = 'body';
      method = 'afterFirstP';
    } else if ($('article').length) {
      $('article').prepend(block + '\n');
      container = 'article';
      method = 'prepend';
    } else if ($('body').length) {
      $('body').prepend(block + '\n');
      container = 'body';
      method = 'prepend';
    } else {
      $.root().prepend(block + '\n');
      container = 'root';
      method = 'prepend';
    }
  } else {
    if ($('article').length) {
      $('article').append('\n' + block);
      container = 'article';
      method = 'append';
    } else if ($('body').length) {
      $('body').append('\n' + block);
      container = 'body';
      method = 'append';
    } else {
      $.root().append('\n' + block);
      container = 'root';
      method = 'append';
    }
  }
  // Для отладки: выводим куда и как вставили
  // eslint-disable-next-line no-console
  console.log(`[insertWidgetHtml] Вставка в <${container}> методом ${method} (${position})`);

  // Возвращаем только содержимое <body> или <article>, если есть, иначе всё содержимое root
  let resultHtml = '';
  if ($('article').length) {
    resultHtml = $('article').html() || '';
  } else if ($('body').length) {
    resultHtml = $('body').html() || '';
  } else {
    resultHtml = $.root().html() || '';
  }
  // Удаляем <!-- /wp:post-content --> из результата на всякий случай
  resultHtml = cleanWpPostContentMarkers(resultHtml);
  return {
    html: resultHtml,
    placement: { container, position, method }
  };
}
