// Tests the pure helpers inside apps_script/Code.gs with FAKE data.  Run: node tests/js/test_code.mjs
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const src = fs.readFileSync(new URL('../../apps_script/Code.gs', import.meta.url), 'utf8');
const ctx = vm.createContext({});
vm.runInContext(src, ctx);
const t = (name, fn) => { fn(); console.log('ok -', name); };

// rows are sheet rows 2.. as [#, Company, POC, Email, Mobile, LinkedIn, Status, Remarks]
const rows = [
  ['1', 'Examplelogix (Example Logistics Pvt. Ltd.)', 'Riya Fakename', 'riya@examplelogix.test', '', '', 'Drafted', ''],
  ['2', 'Acme Inc.', 'Arjun Sampleperson', 'arjun@acme.test', '', '', 'Mailed', ''],
  ['3', '', '', '', '', '', '', ''],
];

t('duplicate by email (case-insensitive)', () => {
  const d = ctx.findDuplicate(rows, 'RIYA@examplelogix.test', 'Other Co');
  assert.equal(d.row, 2); assert.equal(d.by, 'email');
});
t('duplicate by company, different spelling', () => {
  const d = ctx.findDuplicate(rows, 'new@x.test', 'EXAMPLELOGIX Private Limited');
  assert.equal(d.row, 2); assert.equal(d.by, 'company');
  assert.equal(ctx.findDuplicate(rows, 'n@x.test', 'acme').row, 3);
});
t('no duplicate', () => assert.equal(ctx.findDuplicate(rows, 'n@new.test', 'Brand New Co'), null));
t('ignoreRow skips own claimed row', () =>
  assert.equal(ctx.findDuplicate(rows, 'riya@examplelogix.test', 'x', 2), null));
t('first empty row uses Company column; # prefilled rows count as empty', () => {
  assert.equal(ctx.firstEmptyRow(rows), 4);
  assert.equal(ctx.firstEmptyRow([['1', '', '', '', '', '', '', '']]), 2);
  assert.equal(ctx.firstEmptyRow([]), 2);
});
t('template fill escapes HTML, keeps subject plain', () => {
  const h = ctx.fillTemplate('<p>{{Greeting}}</p> invite {{ Company }} to', { Greeting: "Dear Riya ma'am,", Company: 'A&B <Co>' }, true);
  assert.equal(h, '<p>Dear Riya ma&#39;am,</p> invite A&amp;B &lt;Co&gt; to');
  assert.equal(ctx.fillTemplate('Invitation - {{Company}} | BITS', { Company: 'A&B' }, false), 'Invitation - A&B | BITS');
});
t('subject marker stripped', () =>
  assert.equal(ctx.stripMarker('[PU-MASTER] Invitation - {{Company}} | X'), 'Invitation - {{Company}} | X'));
t('mailtrack block + pixel removed, rest kept', () => {
  const html = '<div>Thanks</div><div class="sig"><table><tr><td>Phone</td></tr></table>' +
    '<div class="mt"><img src="https://mailtrack.io/trace/x.png"> Sender notified with <a href="https://mailtrack.io">Mailtrack</a> · Opt out</div></div>';
  const r = ctx.stripMailtrack(html);
  assert.ok(r.removed);
  assert.ok(!/mailtrack|Sender notified/i.test(r.html));
  assert.ok(r.html.includes('Phone') && r.html.includes('Thanks'));
  assert.equal(ctx.stripMailtrack('<p>clean</p>').removed, false);
});
t('base64 normalised: url-safe, standard, padded or not', () => {
  assert.equal(ctx.normB64_('aGk_-w'), 'aGk/+w==');          // url-safe, unpadded
  assert.equal(ctx.normB64_('aGk/+w=='), 'aGk/+w==');        // standard, padded
  assert.equal(ctx.normB64_('aGk/+w'), 'aGk/+w==');          // standard, unpadded
  assert.equal(ctx.normB64_('aG\nk/+w=='), 'aGk/+w==');      // line breaks
  assert.equal(ctx.normB64_(''), '');
});
t('short company / normalise', () => {
  assert.equal(ctx.shortCompany('Examplelogix (Example Logistics Solutions Pvt. Ltd.)'), 'Examplelogix');
  assert.equal(ctx.normaliseCompany('ExampleLogix Pvt. Ltd.'), 'examplelogix');
});

t('snippetAround_ shows split placeholders and missing words', () => {
  assert.match(ctx.snippetAround_('<p>{{<b>Greeting</b>}}</p>', 'Greeting'), /saw: .*Greeting/);
  assert.match(ctx.snippetAround_('<p>hi</p>', 'Greeting'), /does not appear/);
});
console.log('all JS tests passed');
