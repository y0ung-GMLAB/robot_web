import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { indexHtml, stylesCss } from '../tools/index_html.mjs';

const html = indexHtml;
const styles = stylesCss;
const scripts = [
  'motor_config.js',
  'motion_data.js',
  'project_explorer.js',
  'event_log.js',
  'motion_test.js',
].map((name) => readFileSync(new URL(`../static/js/${name}`, import.meta.url), 'utf8')).join('\n');

test('popup UI remains grouped into four management types', () => {
  assert.match(html, /id="operationProgressModal"/);
  assert.match(html, /id="appDialogModal"/);
  assert.match(html, /id="motorErrorPopup"/);
});

test('feature modules do not call native confirm or prompt dialogs', () => {
  assert.doesNotMatch(scripts, /window\.(?:confirm|prompt)\s*\(/);
  assert.match(scripts, /showConfirm/);
  assert.match(scripts, /showPrompt/);
});

test('motor error popup remains visible above every modal type', () => {
  assert.match(
    styles,
    /\.motor-error-popup\s*\{[\s\S]*?z-index:\s*1500;/,
  );
});
