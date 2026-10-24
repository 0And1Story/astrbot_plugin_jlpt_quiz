// Personal-use importer for the public JLPT interactive samples.
// Outputs and downloaded media stay outside the redistributable data/ directory.
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';

const require = createRequire(import.meta.url);
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
let playwright;
try {
  playwright = require(process.env.JLPT_PLAYWRIGHT_MODULE || 'playwright');
} catch (error) {
  if (process.env.JLPT_PLAYWRIGHT_MODULE) throw error;
  playwright = require(path.join(root, 'tmp/tools/node_modules/playwright'));
}
const { chromium } = playwright;
const output = path.resolve(process.argv[2] || path.join(root, 'local_data'));
const relative = path.relative(path.join(root, 'data'), output);
if (!relative || (!relative.startsWith('..' + path.sep) && relative !== '..' && !path.isAbsolute(relative))) {
  throw new Error('Personal-use data must not be written inside the tracked data/ directory.');
}

const vocab = ['vocab_reading', 'vocab_kanji', 'vocab_context', 'vocab_synonym', 'vocab_usage'];
const grammar = ['grammar_fill', 'grammar_order', 'grammar_passage'];
const listenLow = ['listening_task', 'listening_point', 'listening_expression', 'listening_response'];
const listenHigh = ['listening_task', 'listening_point', 'listening_summary', 'listening_response', 'listening_integrated'];
const types = {
  1: ['vocab_reading', 'vocab_context', 'vocab_synonym', 'vocab_usage', ...grammar,
      'reading_short', 'reading_medium', 'reading_long', 'reading_integrated', 'reading_thematic', 'reading_search', ...listenHigh],
  2: ['vocab_reading', 'vocab_kanji', 'vocab_compound', 'vocab_context', 'vocab_synonym', 'vocab_usage', ...grammar,
      'reading_short', 'reading_medium', 'reading_integrated', 'reading_thematic', 'reading_search', ...listenHigh],
  3: [...vocab, ...grammar, 'reading_short', 'reading_medium', 'reading_long', 'reading_search',
      'listening_task', 'listening_point', 'listening_summary', 'listening_expression', 'listening_response'],
  4: [...vocab, ...grammar, 'reading_short', 'reading_medium', 'reading_search', ...listenLow],
  5: [...vocab.slice(0, 4), ...grammar, 'reading_short', 'reading_medium', 'reading_search', ...listenLow],
};
const browser = await chromium.launch({ headless: true,
  ...(process.env.JLPT_BROWSER_CHANNEL ? { channel: process.env.JLPT_BROWSER_CHANNEL } : {}) });
const report = { source: 'https://www.jlpt.jp/e/samples/forlearners.html', files: [], counts: {}, private_only: true };
const questions = [];
try {
  const page = await browser.newPage({ viewport: { width: 1000, height: 1000 }, deviceScaleFactor: 1 });
  for (let level = 1; level <= 5; level++) {
    const base = `https://www.jlpt.jp/e/samples/n${level}/`;
    await page.goto(base + 'index.html', { waitUntil: 'networkidle', timeout: 60000 });
    await page.waitForFunction(() => typeof exportRoot === 'object' && exportRoot.currentFrame >= 9, { timeout: 30000 });
    const response = await page.request.get(base + `n${level}.js`);
    if (!response.ok()) throw new Error(`Cannot download sample definition for N${level}`);
    const source = await response.text();
    const definition = path.join(root, 'tmp/private_sources/official-interactive');
    await fs.mkdir(definition, { recursive: true });
    await fs.writeFile(path.join(definition, `n${level}.js`), source);
    report.files.push({ url: base + `n${level}.js`, sha256: createHash('sha256').update(source).digest('hex') });
    const match = source.match(/^\s*var ans_array = new Array\(([^)]*)\)/m);
    if (!match) throw new Error('Source answer structure changed; manual review required.');
    const answers = match[1].split(',').map(v => Number(v.trim()));
    const count = await page.evaluate(() => Math.max(...exportRoot.getLabels()
      .filter(l => /^ok\d+$/.test(l.label)).map(l => Number(l.label.slice(2)))));
    if (count !== types[level].length || answers.length < count) throw new Error('Question structure changed.');
    for (let num = 1; num <= count; num++) {
      const kind = types[level][num - 1];
      const category = kind.startsWith('vocab_') ? 'vocabulary' : kind.split('_')[0];
      const asset = `official/assets/n${level}`;
      await fs.mkdir(path.join(output, asset), { recursive: true });
      await page.evaluate(n => {
        createjs.Ticker.paused = true;
        window.page_num = n;
        exportRoot.gotoAndStop('p' + n);
        stage.update();
      }, num);
      const image = `${asset}/q${num}.png`;
      await page.locator('canvas').screenshot({ path: path.join(output, image) });
      // Capture full scrollable passages separately, rather than clipping them at the viewport.
      const passages = await page.evaluate(() => {
        const result = [];
        function walk(object) {
          if (!object || object._off || !object.visible || object.alpha === 0) return;
          const text = object.mc_slide_text;
          if (text) {
            const bounds = text.getBounds() || text.nominalBounds;
            if (bounds?.width && bounds?.height) {
              const canvas = document.createElement('canvas');
              canvas.width = Math.ceil(bounds.width * 1.6) + 20;
              canvas.height = Math.ceil(bounds.height * 1.6) + 20;
              const ctx = canvas.getContext('2d');
              ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, canvas.width, canvas.height);
              ctx.scale(1.6, 1.6); ctx.translate(-bounds.x + 5, -bounds.y + 5);
              const mask = text.mask;
              text.mask = null; text.draw(ctx, false); text.mask = mask;
              result.push(canvas.toDataURL());
            }
          }
          for (const child of object.children || []) walk(child);
        }
        walk(exportRoot);
        return result;
      });
      const passageImages = [];
      for (let i = 0; i < passages.length; i++) {
        const name = `${asset}/q${num}-passage${i + 1}.png`;
        await fs.writeFile(path.join(output, name), Buffer.from(passages[i].split(',')[1], 'base64'));
        passageImages.push(name);
      }
      let audio = '';
      let duration = 0;
      if (category === 'listening') {
        audio = `${asset}/q${num}.mp3`;
        const audioUrl = base + `sound/n${num}.mp3`;
        const response = await page.request.get(audioUrl);
        if (!response.ok()) throw new Error(`Audio missing: ${audioUrl}`);
        const bytes = await response.body();
        await fs.writeFile(path.join(output, audio), bytes);
        duration = await page.evaluate(n => {
          const seconds = window['n' + n]?.duration;
          return Number.isFinite(seconds) ? seconds : 0;
        }, num);
        report.files.push({ url: audioUrl, sha256: createHash('sha256').update(bytes).digest('hex') });
      }
      const three = kind === 'listening_expression' || kind === 'listening_response';
      const options = Array.from({ length: three ? 3 : 4 }, (_, i) => `原题选项 ${i + 1}`);
      const answer = answers[num - 1];
      if (!Number.isInteger(answer) || answer < 0 || answer >= options.length) throw new Error('Invalid source answer.');
      const row = { id: `official-sample-N${level}-${num}`, level: `N${level}`, category, question_type: kind,
        prompt: '请按题目图片或音频作答，直接发送原题选项编号。', options, answer,
        explanation: '答案取自 JLPT 官方交互样题判分数据。该来源未提供逐题详细解析。',
        images: category === 'reading' ? [] : [image],
        passage_images: category === 'reading' ? [...passageImages, image] : passageImages,
        audio, audio_duration_seconds: duration, shuffle_options: false,
        source: 'JLPT 官方公开样题（本地自用）', source_url: base + 'index.html',
        license: 'Rights retained by the original owners; local personal-use copy, not for redistribution.' };
      // N1's final listening item contains two linked questions in one audio track.
      if (level === 1 && num === 18) {
        const first = source.match(/window\.toi_bn_press1\s*=\s*function[\s\S]*?if\(n == (\d+)\)/);
        const second = source.match(/window\.toi_bn_press2\s*=\s*function[\s\S]*?if\(n == (\d+)/);
        if (!first || !second) throw new Error('Integrated listening structure changed.');
        for (const [index, match] of [first, second].entries()) {
          questions.push({ ...row, id: row.id + `-${index + 1}`, answer: Number(match[1]),
            prompt: `请回答音频的「質問${index + 1}」，图片含两组问题，请选择对应一组的原题选项编号。` });
        }
      } else questions.push(row);
    }
    report.counts[`N${level}`] = questions.filter(q => q.level === `N${level}`).length;
    console.log(`N${level}: ${report.counts[`N${level}`]} personal-use questions processed`);
  }
  await fs.mkdir(output, { recursive: true });
  await fs.writeFile(path.join(output, 'official.jsonl.tmp'), questions.map(q => JSON.stringify(q)).join('\n') + '\n');
  await fs.rename(path.join(output, 'official.jsonl.tmp'), path.join(output, 'official.jsonl'));
  await fs.mkdir(path.join(root, 'tmp/docs'), { recursive: true });
  await fs.writeFile(path.join(root, 'tmp/docs/official-import.json'), JSON.stringify(report, null, 2));
} finally {
  await browser.close();
}
