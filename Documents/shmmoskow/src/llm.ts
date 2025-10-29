import { OpenAI } from 'openai';

const OPENAI_API_KEY = process.env.OPENAI_API_KEY;
if (!OPENAI_API_KEY) throw new Error('OPENAI_API_KEY не задан в .env');

const openai = new OpenAI({ apiKey: OPENAI_API_KEY });

export interface WidgetChoiceResult {
  best_widget_id: string;
  placement_strategy: 'top' | 'bottom';
  cta_text: string;
}

function normalizePlacementStrategy(raw: string): 'top' | 'bottom' {
  const val = (raw || '').toLowerCase();
  if (val.includes('top') || val.includes('нач')) return 'top';
  if (val.includes('bottom') || val.includes('end') || val.includes('кон')) return 'bottom';
  throw new Error('placement_strategy должен быть top или bottom, а не: ' + raw);
}

export async function pickWidgetByContent(articleText: string, widgets: any[]): Promise<WidgetChoiceResult> {
  const systemPrompt = `Ты — ассистент, который помогает подобрать лучший виджет для статьи. Вот список виджетов (JSON):\n${JSON.stringify(widgets, null, 2)}\n\nДля переданного текста статьи выбери наиболее подходящий виджет (best_widget_id), стратегию размещения (placement_strategy: строго 'top' или 'bottom', без других вариантов) и сгенерируй короткую мотивирующую подводку (cta_text, 1-2 предложения), чтобы читатель захотел кликнуть на виджет. ВНИМАНИЕ: не используй слово 'лидмагнит' или его производные в cta_text. Ответ только в виде JSON.`;

  const userPrompt = `Текст статьи:\n${articleText}`;

  const resp = await openai.chat.completions.create({
    model: 'gpt-4o',
    messages: [
      { role: 'system', content: systemPrompt },
      { role: 'user', content: userPrompt }
    ],
    temperature: 0.2,
    max_tokens: 300
  });

  let text = resp.choices[0]?.message?.content || '';
  // Удаляем markdown-обёртку, если есть
  text = text.trim().replace(/^```json[\r\n]+/i, '').replace(/^```[\r\n]+/i, '').replace(/```\s*$/i, '');
  try {
    const json = JSON.parse(text);
    const placement = normalizePlacementStrategy(json.placement_strategy);
    if (
      typeof json.best_widget_id === 'string' &&
      typeof json.cta_text === 'string'
    ) {
      return {
        best_widget_id: json.best_widget_id,
        placement_strategy: placement,
        cta_text: json.cta_text
      };
    }
    throw new Error('Некорректный формат ответа LLM');
  } catch (e) {
    throw new Error('Ошибка парсинга ответа LLM: ' + text);
  }
}
