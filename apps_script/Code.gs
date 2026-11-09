/**
 * PU Outreach — drafter web app.
 *
 * EVERY team member deploys their OWN copy of this script under their OWN
 * BITS Google account. Deployed as "Execute as: Me", it creates Gmail DRAFTS in
 * the deployer's mailbox and writes rows to the shared sheet. It NEVER sends mail.
 *
 * One-time setup (see TEAM_GUIDE.md):
 *   1. Paste this file into a new Apps Script project; paste appsscript.json too.
 *   2. Put the sheet ID in CONFIG.SHEET_ID below.
 *   3. Run `setupToken` once from the editor; copy the token from the log.
 *   4. Deploy > New deployment > Web app: Execute as "Me", Who has access "Anyone".
 */

const CONFIG = {
  SHEET_ID: 'PASTE_SHEET_ID_HERE',     // the long ID in the sheet URL: /d/<THIS>/edit
  TAB: 'Automation',                   // the ONLY tab this script ever writes to
  MASTER_MARKER: '[PU-MASTER]',        // subject prefix of your master draft
  STATUS_DRAFTED: 'Drafted',
  STATUS_SENT: 'Mailed',
  MAX_ATTACH_BYTES: 25 * 1024 * 1024,  // Gmail's total message size limit
  USE_ADVANCED_READ: false,            // experimental reader (inline images); gave wrong sizes in the first real test
  HEADERS: ['#', 'Company', 'POC', 'Email', 'Mobile', 'LinkedIn', 'Status', 'Remarks'],
};

const COL = { NUM: 1, COMPANY: 2, POC: 3, EMAIL: 4, MOBILE: 5, LINKEDIN: 6, STATUS: 7, REMARKS: 8 };
const NCOLS = 8;
const CODE_VERSION = '0.1.4';

/* ------------------------------------------------------------------ setup */

/** Run once from the editor. Creates (or shows) this member's secret token. */
function setupToken() {
  const props = PropertiesService.getScriptProperties();
  let token = props.getProperty('TOKEN');
  if (!token) {
    token = Utilities.getUuid().replace(/-/g, '') + Utilities.getUuid().replace(/-/g, '');
    props.setProperty('TOKEN', token);
  }
  Logger.log('Your token (paste into `pu-outreach setup`): ' + token);
}

/** Optional: run once to install the "mark as Mailed when sent" checker (every 15 min). */
function installSentChecker() {
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'checkSent')
    .forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('checkSent').timeBased().everyMinutes(15).create();
  Logger.log('Sent checker installed.');
}

/* ------------------------------------------------------------------ entry */

function doPost(e) {
  let req;
  try {
    req = JSON.parse((e && e.postData && e.postData.contents) || '{}');
  } catch (err) {
    return json_({ ok: false, error: 'bad_json' });
  }
  const expected = PropertiesService.getScriptProperties().getProperty('TOKEN');
  if (!expected) return json_({ ok: false, error: 'no_token_configured', fix: 'Run setupToken in the Apps Script editor.' });
  if (!safeEqual_(String(req.token || ''), expected)) return json_({ ok: false, error: 'bad_token' });

  try {
    switch (req.action) {
      case 'ping': return json_({ ok: true, version: CODE_VERSION, user: Session.getEffectiveUser().getEmail() });
      case 'doctor': return json_(doctor_());
      case 'draft': return json_(handleDraft_(req.contact || {}, !!req.dry_run));
      case 'stats': return json_({ ok: true, stats: getStats_() });
      default: return json_({ ok: false, error: 'unknown_action' });
    }
  } catch (err) {
    return json_({ ok: false, error: 'exception', detail: String(err && err.message || err) });
  }
}

function doGet() {
  return ContentService.createTextOutput('PU Outreach drafter is running. Use POST.');
}

/* ------------------------------------------------------------------ draft */

/**
 * contact = { company_full, company_short, poc, email, mobile, linkedin,
 *             greeting, remarks: [..] }
 */
function handleDraft_(c, dryRun) {
  const email = String(c.email || '').trim().toLowerCase();
  const companyFull = String(c.company_full || '').trim();
  const companyShort = String(c.company_short || '').trim() || shortCompany(companyFull);
  const remarks = (c.remarks || []).slice();
  if (!email) return { ok: false, error: 'no_email' };

  const sheet = openTab_();
  const rows = readRows_(sheet);

  const dup = findDuplicate(rows, email, companyFull || companyShort);
  if (dup) return { ok: true, outcome: 'duplicate', duplicate: dup };

  const greeting = String(c.greeting || '').trim() || 'Dear Team,';
  const canDraft = !!companyShort;
  if (!canDraft) remarks.push('needs company name — no draft created');

  let built = null;
  if (canDraft) {
    built = buildDraft_({ greeting: greeting, company: companyShort, email: email });
  }
  if (dryRun) {
    return {
      ok: true, outcome: 'dry_run',
      would_write_row: firstEmptyRow(rows),
      subject: built && built.subject,
      attachments: built && built.attachments.map(b => b.getName()),
      inline_images: built && Object.keys(built.inlineImages).length,
      mailtrack_removed: built && built.mailtrackRemoved,
    };
  }

  // Claim a row first (write-then-verify), so two members racing on the same
  // company/email notice each other. Best effort, see README "Race condition".
  const claim = claimRow_(sheet, {
    company: companyFull || companyShort, poc: c.poc || '', email: email,
    mobile: c.mobile || '', linkedin: c.linkedin || '',
    status: '', remarks: 'creating draft…',
  });
  if (claim.duplicate) return { ok: true, outcome: 'duplicate', duplicate: claim.duplicate };
  const row = claim.row;

  if (!canDraft) {
    writeCells_(sheet, row, { remarks: remarks.join('; ') });
    return { ok: true, outcome: 'row_only', row: row };
  }

  let draft;
  try {
    draft = GmailApp.createDraft(email, built.subject, built.plain, {
      htmlBody: built.html,
      attachments: built.attachments,
      inlineImages: built.inlineImages,
    });
  } catch (err) {
    writeCells_(sheet, row, { remarks: ['draft FAILED: ' + err.message].concat(remarks).join('; ') });
    return { ok: false, error: 'draft_failed', detail: String(err.message), row: row };
  }

  writeCells_(sheet, row, { status: CONFIG.STATUS_DRAFTED, remarks: remarks.join('; ') });
  rememberDraft_(draft.getId(), email, built.subject, built.plain);
  return { ok: true, outcome: 'drafted', row: row, draft_id: draft.getId(), subject: built.subject };
}

/** Clone the master draft with placeholders filled. Never sends. */
function buildDraft_(vals) {
  const master = loadMaster_();
  let html = fillTemplate(master.html, { Greeting: vals.greeting, Company: vals.company }, true);
  let plain = fillTemplate(master.plain, { Greeting: vals.greeting, Company: vals.company }, false);
  const mt = stripMailtrack(html);
  html = mt.html;
  plain = stripMailtrackPlain(plain);
  const subject = fillTemplate(stripMarker(master.subject), { Company: vals.company }, false);
  if (master.totalBytes > CONFIG.MAX_ATTACH_BYTES) {
    throw new Error('attachments total ' + mb_(master.totalBytes) + ' MB exceeds Gmail 25 MB limit');
  }
  return {
    subject: subject, html: html, plain: plain,
    attachments: master.attachments, inlineImages: master.inlineImages,
    mailtrackRemoved: mt.removed,
  };
}

/** Finds the single draft whose subject starts with the marker and reads it fully. */
function loadMaster_() {
  const drafts = GmailApp.getDrafts().filter(d => {
    const s = d.getMessage().getSubject() || '';
    return s.trim().indexOf(CONFIG.MASTER_MARKER) === 0;
  });
  if (drafts.length === 0) throw new Error('no draft with subject starting "' + CONFIG.MASTER_MARKER + '"');
  if (drafts.length > 1) throw new Error(drafts.length + ' drafts start with "' + CONFIG.MASTER_MARKER + '" — keep exactly one');
  const d = drafts[0];
  const msg = d.getMessage();

  if (CONFIG.USE_ADVANCED_READ && typeof Gmail !== 'undefined') {
    try {
      return loadMasterAdvanced_(d.getId(), msg.getId(), msg.getSubject());
    } catch (err) {
      // Don't fail: fall back to the basic reader and say why (doctor shows it).
      const fb = loadMasterBasic_(msg);
      fb.advancedError = String(err && err.message || err);
      return fb;
    }
  }
  return loadMasterBasic_(msg);
}

/** Basic reader (GmailApp only): body, text and normal attachments are kept; inline images are NOT. */
function loadMasterBasic_(msg) {
  const atts = msg.getAttachments({ includeInlineImages: false });
  let inlineCount = 0;
  try { inlineCount = msg.getAttachments({ includeInlineImages: true, includeAttachments: false }).length; } catch (e) {}
  return {
    subject: msg.getSubject(), html: msg.getBody(), plain: msg.getPlainBody(),
    attachments: atts.map(a => a.copyBlob().setName(a.getName())),
    inlineImages: {}, inlineCount: inlineCount,
    totalBytes: atts.reduce((s, a) => s + a.getSize(), 0),
    advanced: false,
  };
}

function loadMasterAdvanced_(draftId, messageId, subject) {
  const res = Gmail.Users.Drafts.get('me', draftId, { format: 'full' });
  messageId = (res.message && res.message.id) || messageId;
  const out = { subject: subject, html: '', plain: '', attachments: [], inlineImages: {}, totalBytes: 0, advanced: true };
  const walk = (part) => {
    const mime = (part.mimeType || '').toLowerCase();
    const headers = {};
    (part.headers || []).forEach(h => { headers[h.name.toLowerCase()] = h.value; });
    const disp = (headers['content-disposition'] || '').toLowerCase();
    const cid = (headers['content-id'] || '').replace(/^<|>$/g, '');
    if (part.parts && part.parts.length) { part.parts.forEach(walk); return; }
    const isFile = !!part.filename || !!(part.body && part.body.attachmentId);
    if (!isFile && mime === 'text/html') { out.html += decodeText_(part.body); return; }
    if (!isFile && mime === 'text/plain') { out.plain += decodeText_(part.body); return; }
    if (!isFile) return;
    let bytes;
    try {
      const b64 = part.body.attachmentId
        ? Gmail.Users.Messages.Attachments.get('me', messageId, part.body.attachmentId).data
        : (part.body.data || '');
      bytes = decodeB64_(b64);
    } catch (err) {
      throw new Error('cannot read draft part "' + (part.filename || mime) + '": ' + err.message);
    }
    const blob = Utilities.newBlob(bytes, part.mimeType, part.filename || cid || 'file');
    out.totalBytes += bytes.length;
    if (cid && disp.indexOf('attachment') !== 0) out.inlineImages[cid] = blob;
    else out.attachments.push(blob);
  };
  walk(res.message.payload);
  return out;
}

function decodeText_(body) {
  if (!body || !body.data) return '';
  return Utilities.newBlob(decodeB64_(body.data)).getDataAsString('UTF-8');
}

/** Gmail returns base64 in either the URL-safe or the standard alphabet, with or without padding
 *  (varies by endpoint). Utilities.base64DecodeWebSafe throws "Could not decode string" on the
 *  wrong one, so normalise first. */
function normB64_(s) {
  let t = String(s || '').replace(/\s+/g, '').replace(/-/g, '+').replace(/_/g, '/').replace(/=+$/, '');
  while (t.length % 4) t += '=';
  return t;
}

function decodeB64_(s) {
  const raw = String(s || '');
  if (!raw) return [];
  // Already-decoded text (contains characters that can't be base64)?
  if (/[^A-Za-z0-9+\/=_\-\s]/.test(raw)) return Utilities.newBlob(raw).getBytes();
  const attempts = [
    () => Utilities.base64Decode(normB64_(raw)),
    () => Utilities.base64DecodeWebSafe(raw),
    () => Utilities.base64Decode(raw),
  ];
  let last;
  for (let i = 0; i < attempts.length; i++) {
    try { return attempts[i](); } catch (e) { last = e; }
  }
  throw new Error(String(last && last.message) + ' [length ' + raw.length + ', starts "' +
                  raw.slice(0, 12).replace(/[^\x20-\x7e]/g, '?') + '"]');
}

/* ------------------------------------------------------------------ sheet */

function openTab_() {
  const ss = SpreadsheetApp.openById(CONFIG.SHEET_ID);
  const sh = ss.getSheetByName(CONFIG.TAB);
  if (!sh) throw new Error('tab "' + CONFIG.TAB + '" not found');
  return sh;
}

/** Returns rows 2..last as arrays of the 8 columns (index 0 = row 2). */
function readRows_(sheet) {
  const last = Math.max(sheet.getLastRow(), 1);
  if (last < 2) return [];
  return sheet.getRange(2, 1, last - 1, NCOLS).getDisplayValues();
}

function writeCells_(sheet, row, v) {
  if (v.status !== undefined) sheet.getRange(row, COL.STATUS).setValue(v.status);
  if (v.remarks !== undefined) sheet.getRange(row, COL.REMARKS).setValue(v.remarks);
}

/** Write the row, flush, re-read and check nobody else claimed the same thing. */
function claimRow_(sheet, v) {
  for (let attempt = 0; attempt < 3; attempt++) {
    const rows = readRows_(sheet);
    const row = firstEmptyRow(rows);
    sheet.getRange(row, COL.MOBILE).setNumberFormat('@');            // keep +91… as text
    sheet.getRange(row, 1, 1, NCOLS).setValues([[
      row - 1, v.company, v.poc, v.email, v.mobile, v.linkedin, v.status, v.remarks,
    ]]);
    SpreadsheetApp.flush();
    Utilities.sleep(400 + Math.floor(Math.random() * 600));
    const after = readRows_(sheet);
    const mine = after[row - 2] || [];
    if (String(mine[COL.EMAIL - 1]).toLowerCase() !== v.email) continue; // overwritten by someone else: retry
    const other = findDuplicate(after, v.email, v.company, row);
    if (other && other.row < row) {                                      // the earlier row wins
      sheet.getRange(row, 2, 1, NCOLS - 1).clearContent();
      return { duplicate: other };
    }
    return { row: row };
  }
  throw new Error('could not claim a row (sheet busy) — try again');
}

/* ------------------------------------------------------------------ doctor */

function doctor_() {
  const checks = [];
  const add = (name, ok, detail) => checks.push({ name: name, ok: !!ok, detail: detail || '' });

  try {
    const sh = openTab_();
    add('Sheet + Automation tab', true, sh.getParent().getName());
    const hdr = sh.getRange(1, 1, 1, NCOLS).getDisplayValues()[0].map(s => s.trim());
    add('Headers A–H', hdr.join('|') === CONFIG.HEADERS.join('|'), hdr.join(' | '));
    const opts = statusOptions_(sh);
    add('Status option "' + CONFIG.STATUS_DRAFTED + '"', opts.indexOf(CONFIG.STATUS_DRAFTED) >= 0, opts.join(', '));
    add('Status option "' + CONFIG.STATUS_SENT + '"', opts.indexOf(CONFIG.STATUS_SENT) >= 0, '');
    add('First empty row', true, String(firstEmptyRow(readRows_(sh))));
  } catch (err) {
    add('Sheet access', false, err.message + ' — check CONFIG.SHEET_ID and that you have edit access');
  }

  add('Web app code version', true, CODE_VERSION + ' (if this is not the latest, redeploy: Deploy > Manage deployments > New version)');
  add('Gmail advanced service', typeof Gmail !== 'undefined',
      typeof Gmail !== 'undefined' ? '' : 'Services > + > Gmail API (needed to keep inline images)');

  try {
    const m = loadMaster_();
    add('Master reader', true, CONFIG.USE_ADVANCED_READ ? 'advanced' : 'basic (GmailApp)');
    if (CONFIG.USE_ADVANCED_READ && typeof Gmail !== 'undefined') {
      add('Gmail advanced read of master', !m.advancedError,
          m.advancedError ? 'FAILED, using basic mode (inline images not kept): ' + m.advancedError : 'ok');
    }
    add('Master draft found', true, m.subject);
    add('Subject has {{Company}}', /\{\{\s*Company\s*\}\}/.test(m.subject), '');
    add('Master body read', m.html.length > 200, m.html.length + ' characters of HTML');
    const hasG = /\{\{\s*Greeting\s*\}\}/.test(m.html);
    const hasC = /\{\{\s*Company\s*\}\}/.test(m.html);
    add('Body has {{Greeting}}', hasG, hasG ? '' : 'not found — ' + snippetAround_(m.html, 'Greeting'));
    add('Body has {{Company}}', hasC, hasC ? '' : 'not found — ' + snippetAround_(m.html, 'Company'));
    add('Attachments', m.attachments.length > 0,
        m.attachments.map(b => b.getName() + ' (' + mb_(b.getBytes().length) + ' MB)').join(', '));
    add('Total size under 25 MB', m.totalBytes <= CONFIG.MAX_ATTACH_BYTES, mb_(m.totalBytes) + ' MB');
    add('Inline images', true, m.advanced
        ? Object.keys(m.inlineImages).length + ' copied'
        : (m.inlineCount || 0) + ' found in master, NOT copied (basic mode)');
    const mt = stripMailtrack(m.html);
    add('Mailtrack footer in saved draft', true, mt.removed ? 'yes — will be removed from copies' : 'not present');
  } catch (err) {
    add('Master draft', false, err.message);
  }
  return { ok: checks.every(c => c.ok), user: Session.getEffectiveUser().getEmail(), checks: checks };
}

/** For doctor: show what the saved HTML really contains around a word (e.g. a placeholder split by formatting). */
function snippetAround_(html, word) {
  const i = String(html || '').indexOf(word);
  if (i < 0) return 'the word "' + word + '" does not appear in the saved HTML at all';
  return 'saw: ' + html.slice(Math.max(0, i - 40), i + word.length + 40).replace(/\s+/g, ' ');
}

function statusOptions_(sh) {
  const rule = sh.getRange(2, COL.STATUS).getDataValidation();
  if (!rule) return [];
  const vals = rule.getCriteriaValues();
  return (vals && Array.isArray(vals[0])) ? vals[0].map(String) : [];
}

/* ------------------------------------------------------------------ sent checker (optional) */

function rememberDraft_(draftId, email, subject, plain) {
  PropertiesService.getScriptProperties().setProperty('d_' + draftId, JSON.stringify({
    email: email, subject: subject, hash: hashText_(plain), ts: Date.now(),
  }));
}

/** Time-driven: marks Status "Mailed" once the draft has been sent. */
function checkSent() {
  const props = PropertiesService.getScriptProperties();
  const all = props.getProperties();
  const stats = getStats_();
  const sh = openTab_();
  Object.keys(all).filter(k => k.indexOf('d_') === 0).forEach(k => {
    const rec = JSON.parse(all[k]);
    if (Date.now() - rec.ts > 30 * 864e5) { props.deleteProperty(k); return; }
    const threads = GmailApp.search('in:sent to:' + rec.email + ' newer_than:30d', 0, 10);
    let sent = null;
    threads.forEach(t => t.getMessages().forEach(m => {
      if (!sent && m.getSubject() === rec.subject && m.getDate().getTime() >= rec.ts) sent = m;
    }));
    if (!sent) return;
    const rows = readRows_(sh);
    for (let i = 0; i < rows.length; i++) {
      if (String(rows[i][COL.EMAIL - 1]).toLowerCase() === rec.email &&
          rows[i][COL.STATUS - 1] === CONFIG.STATUS_DRAFTED) {
        sh.getRange(i + 2, COL.STATUS).setValue(CONFIG.STATUS_SENT);
        break;
      }
    }
    const edited = hashText_(stripMailtrackPlain(sent.getPlainBody())) !== rec.hash;
    stats.sent++; if (edited) stats.edited++; else stats.unedited++;
    props.deleteProperty(k);
  });
  props.setProperty('stats', JSON.stringify(stats));
}

function getStats_() {
  const s = PropertiesService.getScriptProperties().getProperty('stats');
  return s ? JSON.parse(s) : { sent: 0, edited: 0, unedited: 0 };
}

function hashText_(t) {
  const norm = String(t || '').replace(/\s+/g, ' ').trim();
  return Utilities.base64Encode(Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, norm, Utilities.Charset.UTF_8));
}

/* ------------------------------------------------------------------ pure helpers (unit-tested with node) */

const LEGAL_SUFFIX_RE = /\b(private\s+limited|pvt\.?\s*ltd\.?|pvt\.?|ltd\.?|limited|inc\.?|incorporated|llp|llc|corp\.?|corporation|co\.)(?=\s|$|,)/gi;

function shortCompany(name) {
  let s = String(name || '').replace(/\([^)]*\)?/g, ' ');
  s = s.replace(LEGAL_SUFFIX_RE, ' ');
  return s.replace(/[\s,.\-]+$/g, '').replace(/^\s+/, '').replace(/\s+/g, ' ');
}

function normaliseCompany(name) {
  return shortCompany(name).toLowerCase().replace(/[^a-z0-9]/g, '');
}

/** rows: arrays (index 0 = sheet row 2). Returns {row, by, company, status} or null. */
function findDuplicate(rows, email, company, ignoreRow) {
  const e = String(email || '').trim().toLowerCase();
  const n = normaliseCompany(company);
  for (let i = 0; i < rows.length; i++) {
    const row = i + 2;
    if (row === ignoreRow) continue;
    const r = rows[i];
    const rEmail = String(r[COL.EMAIL - 1] || '').trim().toLowerCase();
    const rComp = normaliseCompany(r[COL.COMPANY - 1]);
    if (e && rEmail === e) return { row: row, by: 'email', company: r[COL.COMPANY - 1], status: r[COL.STATUS - 1] };
    if (n && rComp && rComp === n) return { row: row, by: 'company', company: r[COL.COMPANY - 1], status: r[COL.STATUS - 1] };
  }
  return null;
}

/** First sheet row (>=2) whose Company cell is empty. */
function firstEmptyRow(rows) {
  for (let i = 0; i < rows.length; i++) {
    if (!String(rows[i][COL.COMPANY - 1] || '').trim()) return i + 2;
  }
  return rows.length + 2;
}

function fillTemplate(text, vals, isHtml) {
  let out = String(text || '');
  Object.keys(vals).forEach(k => {
    const v = isHtml ? escapeHtml(vals[k]) : String(vals[k]);
    out = out.replace(new RegExp('\\{\\{\\s*' + k + '\\s*\\}\\}', 'g'), () => v);
  });
  return out;
}

function escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function stripMarker(subject) {
  return String(subject || '').replace(CONFIG.MASTER_MARKER, '').trim();
}

/** Removes Mailtrack pixels, links and the "Sender notified with Mailtrack" block. */
function stripMailtrack(html) {
  let out = String(html || '');
  const before = out;
  out = out.replace(/<img\b[^>]*(mailtrack|mltrk)[^>]*>/gi, '');
  // Remove whole enclosing element around the notice text.
  let guard = 0, idx;
  while ((idx = out.search(/Sender notified (with|by)/i)) >= 0 && guard++ < 5) {
    out = removeEnclosing_(out, idx);
  }
  out = out.replace(/<a\b[^>]*mailtrack[^>]*>[\s\S]*?<\/a>/gi, '');
  return { html: out, removed: out !== before };
}

function removeEnclosing_(html, idx) {
  const tags = ['table', 'div', 'p'];
  let best = null;
  tags.forEach(tag => {
    const open = html.lastIndexOf('<' + tag, idx);
    if (open < 0) return;
    // find matching close after idx, respecting nesting
    const re = new RegExp('<(/?)' + tag + '\\b[^>]*>', 'gi');
    re.lastIndex = open;
    let depth = 0, m, end = -1;
    while ((m = re.exec(html))) {
      depth += m[1] ? -1 : 1;
      if (depth === 0) { end = re.lastIndex; break; }
    }
    if (end > idx && (!best || end - open < best.end - best.open)) best = { open: open, end: end };
  });
  if (!best) return html.replace(/Sender notified (with|by)[^<]*/i, '');
  return html.slice(0, best.open) + html.slice(best.end);
}

function stripMailtrackPlain(text) {
  return String(text || '').split(/\r?\n/).filter(l => !/mailtrack|sender notified/i.test(l)).join('\n');
}

function safeEqual_(a, b) {
  if (a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}

function mb_(n) { return (n / 1048576).toFixed(1); }

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
