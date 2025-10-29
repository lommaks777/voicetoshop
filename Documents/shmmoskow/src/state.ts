import fs from 'fs';
import path from 'path';

const statePath = path.resolve(process.cwd(), 'data/state.json');

export function loadState(): any {
  try {
    if (!fs.existsSync(statePath)) return {};
    const raw = fs.readFileSync(statePath, 'utf-8');
    return JSON.parse(raw);
  } catch (e) {
    return {};
  }
}

export function saveState(state: any): void {
  fs.mkdirSync(path.dirname(statePath), { recursive: true });
  fs.writeFileSync(statePath, JSON.stringify(state, null, 2), 'utf-8');
}
