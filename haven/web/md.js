/* Haven markdown renderer: small, hand-written, safe by construction.

   Model output is untrusted. Every piece of text is HTML-escaped before anything else; the renderer only
   ever *builds* a fixed set of tags (p, h1-h6, strong, em, del, code, pre, ul, ol, li, blockquote, table,
   hr, a, button) and never copies HTML from the input. Links get no href at all: only a data-href that the
   app opens on click through pywebview's open_url (https only). No images are loaded, no styles are copied,
   so there is no way to run script or make a network request from model output.

   API:  MD.render(src, opts) -> html string
         MD.split(src)        -> top-level block sources (used to re-render only the block that changed)
         opts.pages: number of pages in the attached document(s); (p. N) citations become chips only when
                     1 <= N <= pages.                                                                       */
(function (root) {
  'use strict';
  const ESC = {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'};
  const esc = s => String(s).replace(/[&<>"']/g, c => ESC[c]);
  const FENCE = /^ {0,3}(`{3,}|~{3,})\s*([\w+#.-]{0,30})?.*$/;
  const HR = /^ {0,3}((\*[ \t]*){3,}|(-[ \t]*){3,}|(_[ \t]*){3,})$/;
  const HEAD = /^ {0,3}(#{1,6})[ \t]+(.*?)[ \t#]*$/;
  const LIST = /^(\s*)([-*+]|\d{1,9}[.)])[ \t]+(.*)$/;
  const QUOTE = /^ {0,3}>[ \t]?(.*)$/;
  const TSEP = /^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$/;
  const P0 = '\u0000';

  /* ---------- math (KaTeX, vendored in /web/vendor/katex; works offline) ----------
     trust:false keeps \href, \url, \includegraphics and \html* commands disabled, so model output can't
     add links, images or styles through math; maxExpand/maxSize stop macro bombs. Without KaTeX the
     formula is shown as code instead. */
  const MATH_OPEN = /^\s*(\$\$|\\\[)\s*$/, MATH_CLOSE = /^\s*(\$\$|\\\])\s*$/;
  function math(tex, display) {
    tex = String(tex).trim();
    if (!tex) return '';
    const k = root.katex;
    if (k && k.renderToString) {
      try {
        const html = k.renderToString(tex, {displayMode: !!display, throwOnError: false, trust: false, strict: 'ignore',
                                            maxSize: 20, maxExpand: 500, output: 'htmlAndMathml'});
        return display ? `<div class="math-block">${html}</div>` : `<span class="math">${html}</span>`;
      } catch (e) { /* fall through */ }
    }
    return display ? `<pre class="math-raw"><code>${esc(tex)}</code></pre>` : `<code class="math-raw">${esc(tex)}</code>`;
  }

  /* ---------- blocks ---------- */
  function split(src) {
    const lines = String(src || '').replace(/\r\n?/g, '\n').split('\n');
    const out = [];
    let cur = [], fence = null, mblock = false;
    const flush = () => { if (cur.length) { out.push(cur.join('\n')); cur = []; } };
    for (const ln of lines) {
      if (fence) {
        cur.push(ln);
        const m = ln.match(/^ {0,3}(`{3,}|~{3,})\s*$/);
        if (m && m[1][0] === fence[0] && m[1].length >= fence.length) { fence = null; flush(); }
        continue;
      }
      if (mblock) {  // a $$ ... $$ or \[ ... \] block spanning several lines
        cur.push(ln);
        if (MATH_CLOSE.test(ln)) { mblock = false; flush(); }
        continue;
      }
      if (MATH_OPEN.test(ln)) { flush(); mblock = true; cur.push(ln); continue; }
      const f = ln.match(FENCE);
      if (f) { flush(); fence = f[1]; cur.push(ln); continue; }
      if (!ln.trim()) { flush(); continue; }
      cur.push(ln);
    }
    flush();
    return out;
  }

  function render(src, opts) {
    opts = opts || {};
    return split(src).map(b => block(b, opts, 0)).join('');
  }

  function block(b, o, depth) {
    const lines = b.split('\n');
    if (MATH_OPEN.test(lines[0])) {
      const closed = lines.length > 1 && MATH_CLOSE.test(lines[lines.length - 1]);
      const body = lines.slice(1, closed ? -1 : undefined).join('\n');
      // still streaming (no closing line yet): show the formula as text until it is complete
      return closed ? math(body, true) : `<p class="math-pending">${esc(lines.join('\n'))}</p>`;
    }
    const f = lines[0].match(FENCE);
    if (f) {
      let body = lines.slice(1);
      const last = body[body.length - 1];
      if (body.length && /^ {0,3}(`{3,}|~{3,})\s*$/.test(last || '')) body = body.slice(0, -1);
      const lang = (f[2] || '').slice(0, 20);
      return `<div class="code"><div class="code-h"><span>${esc(lang || 'code')}</span><button class="cp" type="button">Copy</button></div><pre><code>${esc(body.join('\n'))}</code></pre></div>`;
    }
    let html = '', i = 0;
    while (i < lines.length) {
      const ln = lines[i];
      let m;
      if ((m = ln.match(HEAD))) { const n = m[1].length; html += `<h${n}>${inline(m[2], o)}</h${n}>`; i++; continue; }
      if (HR.test(ln)) { html += '<hr>'; i++; continue; }
      if (QUOTE.test(ln)) {
        const q = [];
        while (i < lines.length && QUOTE.test(lines[i])) q.push(lines[i++].match(QUOTE)[1]);
        html += `<blockquote>${depth < 5 ? render(q.join('\n'), o) : `<p>${inline(q.join(' '), o)}</p>`}</blockquote>`;
        continue;
      }
      if (ln.includes('|') && i + 1 < lines.length && TSEP.test(lines[i + 1]) && lines[i + 1].includes('-')) {
        const rows = [ln];
        i += 2;
        while (i < lines.length && lines[i].includes('|')) rows.push(lines[i++]);
        html += table(rows, o);
        continue;
      }
      if (LIST.test(ln)) {
        const items = [];
        while (i < lines.length) {
          const l = lines[i], lm = l.match(LIST);
          if (lm) items.push({ind: lm[1].replace(/\t/g, '    ').length, ord: /\d/.test(lm[2]), num: parseInt(lm[2], 10), text: lm[3]});
          else if (items.length && /^\s+\S/.test(l)) items[items.length - 1].text += ' ' + l.trim();
          else break;
          i++;
        }
        html += list(items, 0, o).html;
        continue;
      }
      const para = [];
      while (i < lines.length && !HEAD.test(lines[i]) && !HR.test(lines[i]) && !QUOTE.test(lines[i]) && !LIST.test(lines[i]) &&
             !(lines[i].includes('|') && i + 1 < lines.length && TSEP.test(lines[i + 1]) && lines[i + 1].includes('-'))) para.push(lines[i++]);
      if (para.length) html += `<p>${para.map(p => inline(p, o)).join('<br>')}</p>`;
      else i++;
    }
    return html;
  }

  function list(items, start, o) {
    const base = items[start].ind, ord = items[start].ord;
    let html = ord ? `<ol${items[start].num > 1 ? ` start="${items[start].num | 0}"` : ''}>` : '<ul>';
    let i = start;
    while (i < items.length && items[i].ind >= base) {
      if (items[i].ind > base) { // nested list under the previous item
        const sub = list(items, i, o);
        html = html.replace(/<\/li>$/, sub.html + '</li>');
        i = sub.next;
        continue;
      }
      if (items[i].ord !== ord && i > start) break;
      html += `<li>${inline(items[i].text, o)}</li>`;
      i++;
    }
    return {html: html + (ord ? '</ol>' : '</ul>'), next: i};
  }

  function cells(row) {
    let r = row.trim();
    if (r.startsWith('|')) r = r.slice(1);
    if (r.endsWith('|')) r = r.slice(0, -1);
    return r.split('|').map(c => c.trim());
  }

  function table(rows, o) {
    const head = cells(rows[0]);
    let h = '<div class="tbl"><table><thead><tr>' + head.map(c => `<th>${inline(c, o)}</th>`).join('') + '</tr></thead><tbody>';
    for (const r of rows.slice(1)) {
      const c = cells(r);
      h += '<tr>' + head.map((_, k) => `<td>${inline(c[k] || '', o)}</td>`).join('') + '</tr>';
    }
    return h + '</tbody></table></div>';
  }

  /* ---------- inline ---------- */
  function safeUrl(raw) {
    let u;
    try { u = new URL(raw); } catch (e) { return null; }
    if (u.protocol === 'https:' || u.protocol === 'http:') return u;
    return null; // javascript:, data:, file:, vbscript:, blob: ... never become links
  }

  function link(text, url, o) {
    const u = safeUrl(url);
    const label = text === null ? esc(url) : inlineText(text, o);
    if (!u) return label;
    if (u.protocol === 'https:') return `<a class="lnk" data-href="${esc(u.href)}" title="${esc(u.href)}">${label}</a>`;
    return `<span class="lnk-http" title="Not opened automatically: this link is not secure (http)">${label}${text === null ? '' : ` (${esc(u.href)})`}</span>`;
  }

  function inlineText(s, o) { // emphasis only (used inside link labels)
    return emph(esc(s), o);
  }

  function emph(h, o) {
    h = h.replace(/\*\*([^*\n]+?)\*\*/g, '<strong>$1</strong>')
         .replace(/__([^_\n]+?)__/g, '<strong>$1</strong>')
         .replace(/(^|[^*\w])\*([^*\s][^*\n]*?)\*(?!\*)/g, '$1<em>$2</em>')
         .replace(/(^|[^_\w])_([^_\s][^_\n]*?)_(?![_\w])/g, '$1<em>$2</em>')
         .replace(/~~([^~\n]+?)~~/g, '<del>$1</del>');
    if (o && o.pages) h = cites(h, o);
    return h;
  }

  // (p. 12)  (pp. 3–5)  (p. 4, 7)  -> chips, only for pages that exist
  function cites(h, o) {
    return h.replace(/\((pp?)\.\s?(\d{1,5}(?:\s?[–-]\s?\d{1,5})?(?:\s?,\s?\d{1,5}(?:\s?[–-]\s?\d{1,5})?)*)\)/g, (all, _p, list) => {
      const parts = list.split(/\s?,\s?/);
      const chips = [];
      for (const part of parts) {
        const r = part.split(/\s?[–-]\s?/).map(Number);
        const a = r[0], b = r[1] || r[0];
        if (!(a >= 1 && b >= a && b <= o.pages)) return all; // any page out of range: leave the whole thing as text
        chips.push(`<button type="button" class="cite" data-p="${a}">${a === b ? 'p. ' + a : 'pp. ' + a + '–' + b}</button>`);
      }
      return chips.join('');
    });
  }

  // Runs of 1,000+ characters with no spaces (base64, minified code, garbage) can't be wrapped cheaply:
  // the browser would spend seconds on line breaking. Show them in a horizontally scrolling box instead,
  // and only the first LONG_SHOW characters of a gigantic run (Copy still copies the full text).
  const LONG = 1000, LONG_SHOW = 20000;
  function longRun(r) {
    const shown = r.length > LONG_SHOW ? r.slice(0, LONG_SHOW) : r;
    const more = r.length - shown.length;
    return `<span class="longrun">${esc(shown)}</span>` + (more ? `<span class="longmore">… ${more.toLocaleString()} more characters (Copy gets all of it)</span>` : '');
  }

  function inline(s, o) {
    s = String(s).replace(/\u0000/g, '');
    const keep = [];
    const put = html => { keep.push(html); return P0 + (keep.length - 1) + P0; };
    if (s.length >= LONG) s = s.replace(/\S{1000,}/g, r => /^https?:\/\//.test(r) && r.length < 2000 ? r : put(longRun(r)));
    s = s.replace(/(`+)([^`\n]+?)\1/g, (_, _t, c) => put(`<code>${esc(c)}</code>`));
    // math: \$ is a literal dollar; $$..$$ and \[..\] display, \(..\) and $..$ inline.
    // A $..$ pair must hug its content ("$x$", not "$5 and $10") and not be followed by a digit.
    if (s.includes('$') || s.includes('\\(') || s.includes('\\[')) {
      s = s.replace(/\\\$/g, () => put('$'));
      s = s.replace(/\$\$([^$]+?)\$\$/g, (_, t) => put(math(t, true)));
      s = s.replace(/\\\[([\s\S]+?)\\\]/g, (_, t) => put(math(t, true)));
      s = s.replace(/\\\(([\s\S]+?)\\\)/g, (_, t) => put(math(t, false)));
      s = s.replace(/(^|[^\w$])\$(?=[^\s$])([^$\n]{0,800}?[^\s\\$])\$(?![\w$])/g, (all, pre, t) => pre + put(math(t, false)));
      s = s.replace(/(^|[^\w$])\$([^\s$\\])\$(?![\w$])/g, (all, pre, t) => pre + put(math(t, false)));  // single character, e.g. $x$
    }
    s = s.replace(/!\[([^\]\n]{0,300})\]\(([^()\s]{1,2000})(?:\s+"[^"\n]*")?\)/g, (_, alt) => put(`<span class="img-alt">[image${alt ? ': ' + esc(alt) : ''}]</span>`));
    s = s.replace(/\[([^\]\n]{1,500})\]\(([^()\s]{1,2000})(?:\s+"[^"\n]*")?\)/g, (_, t, u) => put(link(t, u, o)));
    s = s.replace(/\bhttps?:\/\/[^\s<>()"'`]{1,2000}[^\s<>()"'`.,;:!?]/g, u => put(link(null, u, o)));
    let h = emph(esc(s), o);
    for (let n = 0; n < 4 && h.includes(P0); n++) h = h.replace(/\u0000(\d+)\u0000/g, (_, k) => keep[+k] || ''); // nested (code in a link label)
    return h.replace(/\u0000/g, '');
  }

  root.MD = {render, split, esc, inline};
})(typeof window !== 'undefined' ? window : globalThis);
