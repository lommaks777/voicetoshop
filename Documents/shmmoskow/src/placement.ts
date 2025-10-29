import fs from 'fs';
import path from 'path';

export interface WidgetInfo {
  id: string;
  type: string;
  topics: string[];
  embed_html: string;
  default_placement: 'top' | 'bottom';
}

export function getWidgetHtmlById(widgetId: string): { embed_html: string; default_placement: 'top' | 'bottom' } {
  const widgetsPath = path.resolve(process.cwd(), 'widgets.json');
  const widgets: WidgetInfo[] = JSON.parse(fs.readFileSync(widgetsPath, 'utf-8'));
  const widget = widgets.find(w => w.id === widgetId);
  if (!widget) throw new Error(`Виджет с id=${widgetId} не найден в widgets.json`);
  return {
    embed_html: widget.embed_html,
    default_placement: widget.default_placement
  };
}
