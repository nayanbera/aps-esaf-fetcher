/* Drag-and-drop column reordering — auto-initialised for any
 * <table id="..." data-col-reorder>.  Drag a header cell onto another to move
 * the column; the order is saved per table in this browser (localStorage).
 *
 * Columns are identified by header text (or data-col="..." on the <th>), so
 * adding a column later does not invalidate saved orders.  Rows that don't have
 * one cell per column (colspan rows, detail rows) are left alone.  A
 * MutationObserver re-applies the order whenever HTMX swaps rows or a whole
 * table is replaced.
 */
(function () {
  'use strict';

  var PREFIX = 'colorder:';

  var style = document.createElement('style');
  style.textContent =
    'table[data-col-reorder] thead th[draggable]{cursor:grab;user-select:none}' +
    'table[data-col-reorder] thead th.col-drag-over{box-shadow:inset 3px 0 0 #0d6efd}' +
    'table[data-col-reorder] thead th.col-dragging{opacity:.5}';
  document.head.appendChild(style);

  var drag = null;   // {table, ci} while a header is being dragged

  // Tables sharing data-col-key (e.g. one table per group) share one saved order.
  function key(t) { return t.getAttribute('data-col-key') || t.id; }

  function load(id) {
    try { return JSON.parse(localStorage.getItem(PREFIX + id)) || null; } catch (e) { return null; }
  }
  function save(id, ids) {
    try { localStorage.setItem(PREFIX + id, JSON.stringify(ids)); } catch (e) { /* private mode */ }
  }
  function clear(id) {
    try { localStorage.removeItem(PREFIX + id); } catch (e) { /* ignore */ }
  }

  function headerCells(t) {
    var r = t.tHead && t.tHead.rows[0];
    return r ? Array.prototype.slice.call(r.cells) : [];
  }

  // Display order as an array of original column indexes.
  function currentOrder(t) {
    var st = t._cr, order = [], used = {};
    (st.saved || []).forEach(function (id) {
      var ci = st.ids.indexOf(id);
      if (ci >= 0 && !used[ci]) { order.push(ci); used[ci] = true; }
    });
    for (var i = 0; i < st.n; i++) if (!used[i]) order.push(i);   // new/unknown columns go last
    return order;
  }

  function isDefault(order) {
    return order.every(function (ci, i) { return ci === i; });
  }

  function reorderRow(tr, order, n) {
    var cells = Array.prototype.slice.call(tr.cells);
    if (cells.length !== n) return;                                   // colspan / detail rows
    for (var k = 0; k < n; k++) if (cells[k].colSpan > 1) return;
    // A freshly rendered row arrives in original order: stamp its cells.
    if (!cells[0].hasAttribute('data-ci')) {
      for (var j = 0; j < n; j++) cells[j].setAttribute('data-ci', j);
    }
    var byCi = {};
    for (var m = 0; m < n; m++) byCi[cells[m].getAttribute('data-ci')] = cells[m];
    var wanted = order.map(function (ci) { return byCi[ci]; });
    if (wanted.some(function (c) { return !c; })) return;             // inconsistent row — skip
    var inOrder = wanted.every(function (c, i) { return c === cells[i]; });
    if (inOrder) return;                                              // no DOM change → no observer loop
    wanted.forEach(function (c) { tr.appendChild(c); });
  }

  function apply(t) {
    var order = currentOrder(t), n = t._cr.n;
    Array.prototype.forEach.call(t.rows, function (tr) { reorderRow(tr, order, n); });
    if (t._cr.resetBtn) t._cr.resetBtn.hidden = isDefault(order);
  }

  function addResetButton(t) {
    Array.prototype.forEach.call(
      document.querySelectorAll('button[data-col-reset="' + t.id + '"]'),
      function (b) { b.remove(); });                                  // orphan from a replaced table
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn btn-link btn-sm p-0 mb-1 text-muted';
    btn.setAttribute('data-col-reset', t.id);
    btn.hidden = true;
    btn.innerHTML = '<i class="bi bi-arrow-counterclockwise me-1"></i>Reset column order';
    btn.addEventListener('click', function () {
      clear(key(t));
      t._cr.saved = null;
      apply(t);
    });
    var host = t.closest('.table-responsive') || t;
    host.parentNode.insertBefore(btn, host);
    t._cr.resetBtn = btn;
  }

  function init(t) {
    var ths = headerCells(t);
    if (!t.id || !ths.length) return;
    if (!t._cr) {
      var seen = {};
      var ids = ths.map(function (th, i) {
        var id = th.getAttribute('data-col') || th.textContent.replace(/\s+/g, ' ').trim() || ('col' + i);
        if (seen[id]) id += '#' + i;
        seen[id] = true;
        return id;
      });
      t._cr = { ids: ids, n: ths.length, saved: load(key(t)), resetBtn: null };
      ths.forEach(function (th, i) {
        th.setAttribute('data-ci', i);
        th.draggable = true;
        th.title = (th.title ? th.title + ' — ' : '') + 'Drag to reorder column';
      });
      bindDrag(t);
      addResetButton(t);
    }
    apply(t);
  }

  function bindDrag(t) {
    var head = t.tHead;
    function th(e) { var c = e.target.closest && e.target.closest('th'); return c && head.contains(c) ? c : null; }
    function clearMarks() {
      Array.prototype.forEach.call(head.querySelectorAll('.col-drag-over,.col-dragging'),
        function (c) { c.classList.remove('col-drag-over', 'col-dragging'); });
    }

    head.addEventListener('dragstart', function (e) {
      var c = th(e); if (!c) return;
      drag = { table: t, ci: Number(c.getAttribute('data-ci')) };
      c.classList.add('col-dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', String(drag.ci));          // required by Firefox
    });
    head.addEventListener('dragover', function (e) {
      var c = th(e); if (!c || !drag || drag.table !== t) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      Array.prototype.forEach.call(head.querySelectorAll('.col-drag-over'),
        function (x) { if (x !== c) x.classList.remove('col-drag-over'); });
      c.classList.add('col-drag-over');
    });
    head.addEventListener('drop', function (e) {
      var c = th(e); if (!c || !drag || drag.table !== t) return;
      e.preventDefault();
      var order = currentOrder(t);
      var from = order.indexOf(drag.ci), to = order.indexOf(Number(c.getAttribute('data-ci')));
      if (from >= 0 && to >= 0 && from !== to) {
        order.splice(to, 0, order.splice(from, 1)[0]);
        t._cr.saved = order.map(function (ci) { return t._cr.ids[ci]; });
        save(key(t), t._cr.saved);
        apply(t);
      }
      clearMarks();
    });
    head.addEventListener('dragend', function () { drag = null; clearMarks(); });
  }

  function scan() {
    Array.prototype.forEach.call(document.querySelectorAll('table[data-col-reorder]'), init);
  }

  var pending = false;
  function schedule() {
    if (pending) return;
    pending = true;
    (window.requestAnimationFrame || setTimeout)(function () { pending = false; scan(); });
  }

  function start() {
    scan();
    new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
