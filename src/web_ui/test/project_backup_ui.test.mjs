/** 프로젝트 자동 백업 목록 · 수정 목록 33-4 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { indexHtml } from '../tools/index_html.mjs';

test('auto backup list sits next to the trash and links each project zip', () => {
  assert.match(indexHtml, /<button id="projectBackupsButton" type="button"/);
  assert.match(indexHtml, /<div id="projectBackupsList" class="project-usb-help hidden"><\/div>/);
  const api = readFileSync(new URL('../static/js/api.js', import.meta.url), 'utf8');
  assert.match(api, /request\('GET', '\/api\/project-backups'\)/);
  const explorer = readFileSync(new URL('../static/js/project_explorer.js', import.meta.url), 'utf8');
  assert.match(explorer, /projectBackupUrl\(day\.day, item\.project_id\)/);
  assert.match(explorer, /el\.projectBackupsButton\?\.addEventListener\('click', \(\) => renderBackups\(true\)\)/);
});
