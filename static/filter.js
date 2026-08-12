/* Regex table filter — auto-initialised for any .table-regex-filter input.
 * data-target="<table-element-id>" on the input tells it which table to filter.
 */
(function () {
  'use strict';

  function applyFilter(input) {
    var tableId = input.dataset.target;
    var table   = tableId ? document.getElementById(tableId) : null;
    if (!table) return;

    var pattern = input.value;
    var re      = null;
    var countEl = input.closest('.filter-wrap') &&
                  input.closest('.filter-wrap').querySelector('.filter-count');

    if (pattern) {
      try {
        re = new RegExp(pattern, 'i');
        input.classList.remove('is-invalid');
        input.classList.add('is-valid');
      } catch (e) {
        input.classList.remove('is-valid');
        input.classList.add('is-invalid');
        if (countEl) countEl.textContent = 'invalid regex';
        return;
      }
    } else {
      input.classList.remove('is-invalid', 'is-valid');
    }

    var rows    = table.querySelectorAll('tbody > tr');
    var visible = 0;
    var total   = 0;

    rows.forEach(function (row) {
      /* Rows marked data-follow-prev are synced to their parent later, not filtered independently */
      if (row.hasAttribute('data-follow-prev')) return;

      /* Skip placeholder rows (single cell spanning all columns) */
      if (row.cells.length <= 1) {
        row.style.display = (!re || visible === 0) ? '' : 'none';
        return;
      }
      total++;
      var text = Array.from(row.cells).map(function (c) {
        return c.textContent;
      }).join('\t');
      var show = !re || re.test(text);
      row.style.display = show ? '' : 'none';
      if (show) visible++;
    });

    /* Update placeholder visibility: show only when no real rows are visible */
    rows.forEach(function (row) {
      if (row.hasAttribute('data-follow-prev')) return;
      if (row.cells.length <= 1) {
        row.style.display = (re && visible === 0) ? '' : (re ? 'none' : '');
      }
    });

    /* Sync data-follow-prev rows to their preceding sibling's visibility */
    rows.forEach(function (row) {
      if (!row.hasAttribute('data-follow-prev')) return;
      var prev = row.previousElementSibling;
      row.style.display = (prev && prev.style.display === 'none') ? 'none' : '';
    });

    if (countEl) {
      countEl.textContent = re
        ? (visible + ' / ' + total)  /* narrow no-break spaces */
        : (total + ' rows');
    }
  }

  function init() {
    document.querySelectorAll('.table-regex-filter').forEach(function (input) {
      /* Initial count */
      applyFilter(input);

      input.addEventListener('input', function () { applyFilter(this); });

      /* Clear button */
      var clearBtn = input.closest('.filter-wrap') &&
                     input.closest('.filter-wrap').querySelector('.filter-clear');
      if (clearBtn) {
        clearBtn.addEventListener('click', function () {
          input.value = '';
          applyFilter(input);
          input.focus();
        });
      }
    });

    /* Re-apply all filters after HTMX swaps (rows added / replaced) */
    document.body.addEventListener('htmx:afterSettle', function () {
      document.querySelectorAll('.table-regex-filter').forEach(applyFilter);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
