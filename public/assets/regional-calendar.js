(function () {
  'use strict';
  const C = window.KendoCalendarCore;
  const payload = JSON.parse(document.getElementById('regional-data').textContent);
  const today = C.todayJst();
  for (const [key, value] of Object.entries(payload.categories)) C.CATEGORIES[key] = value.types;
  Object.assign(C.PARTICIPATION, payload.participationLabels);
  const cardTemplates = new Map(Array.from(document.querySelectorAll('#static-fallback .card'), card => [card.dataset.eventId, card]));
  const weekdays = ['日', '月', '火', '水', '木', '金', '土'];
  const initialScope = payload.region;
  const state = {
    scope: initialScope, view: 'calendar', period: window.matchMedia('(max-width: 520px)').matches ? 'weekend' : 'month',
    month: today.slice(0, 7), weekend: C.weekendOf(today), selectedDate: today, focusEvent: '',
    prefecture: '', category: 'all', participation: '', organization: '', keyword: ''
  };
  function el(id) {return document.getElementById(id);}
  function escapeHtml(value) {
    return String(value == null ? '' : value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#039;');
  }
  function dateLabel(date, withYear) {
    const d = C.parseDate(date);
    if (!d) return '';
    return (withYear ? d.getUTCFullYear() + '年' : '') + (d.getUTCMonth() + 1) + '月' + d.getUTCDate() + '日（' + weekdays[d.getUTCDay()] + '）';
  }
  function shortDate(date) {
    const d = C.parseDate(date);
    return (d.getUTCMonth() + 1) + '/' + d.getUTCDate() + '（' + weekdays[d.getUTCDay()] + '）';
  }
  function periodBounds() {return state.period === 'month' ? C.monthBounds(state.month) : state.weekend;}
  function scopeEvents() {return C.filterEvents(payload.events, {scope: state.scope, today});}
  function filteredEvents() {
    return C.filterEvents(payload.events, Object.assign({}, state, periodBounds(), {today}));
  }
  function timeLabel(event) {
    return event.start_time ? event.start_time + (event.end_time ? '–' + event.end_time : '') : '時間未定';
  }
  function statusHtml(event) {
    const type = C.participationType(event);
    let html = '<span class="status-badge status-badge--' + type + '">' + escapeHtml(C.PARTICIPATION[type]) + '</span>';
    if (event.application_required === true && type !== 'registration_required') {
      html += '<span class="status-badge status-badge--registration_required">申込必須</span>';
    }
    return html;
  }
  function cardHtml(event) {
    const original = cardTemplates.get(String(event.event_id));
    if (!original) throw new Error('Static event card is missing');
    const card = original.cloneNode(true);
    card.id = 'event-' + event.event_id;
    card.tabIndex = -1;
    card.classList.toggle('is-focused', state.focusEvent === event.event_id);
    return card.outerHTML;
  }
  function emptyHtml(dateOnly) {
    return '<div class="result-empty"><p>' + (dateOnly ? '選択した日には、この条件に合う掲載情報がありません。' : 'この期間には、この条件に合う掲載情報がありません。') +
      '</p><p>ほかの日付や地域、参加条件もお試しください。</p><button type="button" data-action="reset-filters">絞り込みを解除する</button></div>';
  }
  function chooseDate(events, force) {
    const bounds = periodBounds();
    if (force || !state.selectedDate || state.selectedDate < today || state.selectedDate < bounds.from || state.selectedDate > bounds.to) {
      state.selectedDate = events[0] ? events[0].event_date : (bounds.from < today && today <= bounds.to ? today : bounds.from);
    }
  }
  function updateOptions() {
    const events = scopeEvents();
    const previousOrg = state.organization;
    const ids = new Set(events.map(event => event.organization_id));
    const organizations = payload.organizations.filter(org => ids.has(org.organization_id));
    el('filter-organization').innerHTML = '<option value="">すべての団体</option>' + organizations.map(org => '<option value="' + escapeHtml(org.organization_id) + '">' + escapeHtml(org.name) + '</option>').join('');
    state.organization = ids.has(previousOrg) ? previousOrg : '';
    el('filter-organization').value = state.organization;
    el('filter-prefecture').innerHTML = state.scope === 'tokyo' ? '<option value="東京都">東京都</option>' :
      '<option value="">関東のすべての都県</option>' + C.PREFECTURES.map(pref => '<option value="' + pref + '">' + pref + '</option>').join('');
    el('filter-prefecture').disabled = state.scope === 'tokyo';
    el('filter-prefecture').value = state.scope === 'tokyo' ? '東京都' : state.prefecture;
  }
  function updateRegion() {
    const events = scopeEvents();
    el('scope-total').textContent = events.length;
    el('scope-org-total').textContent = new Set(events.map(event => event.organization_id)).size;
  }
  function monthHtml(events) {
    const grouped = C.groupByDate(events);
    const days = C.monthDays(state.month);
    const rows = [];
    for (let offset = 0; offset < days.length; offset += 7) {
      rows.push('<tr>' + days.slice(offset, offset + 7).map(date => {
        const day = C.parseDate(date);
        const outside = date.slice(0, 7) !== state.month;
        const items = grouped.get(date) || [];
        const summary = C.visibleDaySummary(items, 2);
        const selected = date === state.selectedDate;
        const label = dateLabel(date, true) + '、掲載' + items.length + '件' + (date < today ? '、過去の日付' : '');
        const classes = 'calendar-day' + (outside ? ' is-outside' : '') + (day.getUTCDay() === 0 ? ' is-sunday' : '');
        const snippets = summary.shown.map(event => '<span class="calendar-day__item' + (event.event_type === 'adult_renseikai' ? ' is-renseikai' : '') +
          '">' + escapeHtml((event.start_time || '未定') + ' ' + C.prefecture(event) + ' ' + event.organization_name) + '</span>').join('');
        return '<td><button type="button" class="' + classes + '" data-date="' + date + '" aria-label="' + escapeHtml(label) +
          '" aria-pressed="' + selected + '" tabindex="' + (selected ? '0' : '-1') + '"' + (date < today || outside ? ' disabled' : '') + '>' +
          '<span class="calendar-day__top"><span class="calendar-day__number">' + day.getUTCDate() + '</span>' +
          (date === today ? '<span class="calendar-day__today">今日</span>' : '') + '</span>' + snippets +
          (items.length ? '<span class="calendar-day__mobile-count">' + items.length + '件</span>' : '') +
          (summary.remaining ? '<span class="calendar-day__more">ほか' + summary.remaining + '件</span>' : '') + '</button></td>';
      }).join('') + '</tr>');
    }
    return '<table class="month-calendar"><caption>' + escapeHtml(state.month) + 'の掲載予定。日付を選ぶと詳細を表示します。</caption><thead><tr>' +
      ['月','火','水','木','金','土','日'].map(day => '<th scope="col">' + day + '</th>').join('') + '</tr></thead><tbody>' + rows.join('') + '</tbody></table>';
  }
  function weekendHtml(events) {
    const grouped = C.groupByDate(events);
    return '<div class="weekend-grid">' + [state.weekend.from, state.weekend.to].map(date => {
      const items = grouped.get(date) || [];
      const contents = items.length ? '<div class="weekend-mini-list">' + items.map(event =>
        '<button type="button" class="weekend-event" data-event="' + escapeHtml(event.event_id) + '" aria-label="' + escapeHtml(event.title + 'の詳細を表示') + '">' +
        '<span class="weekend-event__time">' + escapeHtml(timeLabel(event)) + '</span>' +
        '<span class="weekend-event__title">' + escapeHtml(event.title) + '</span>' +
        '<span class="weekend-event__venue">' + escapeHtml(event.area + ' · ' + (event.venue || '会場未確認')) + '</span>' +
        statusHtml(event) + '</button>').join('') + '</div>' :
        '<div class="weekend-empty"><p>' + (date < today ? '過去の日程は表示していません。' : 'この条件での掲載はありません。') + '</p></div>';
      return '<section class="weekend-column" aria-label="' + escapeHtml(dateLabel(date, false)) + '">' +
        '<div class="weekend-day-heading"><button type="button" data-date="' + date + '" aria-pressed="' + (state.selectedDate === date) + '"' +
        (date < today ? ' disabled' : '') + '>' + escapeHtml(shortDate(date)) + '</button><span>' + items.length + '件</span></div>' + contents + '</section>';
    }).join('') + '</div>';
  }
  function renderList(events) {
    if (!events.length) return emptyHtml(false);
    return Array.from(C.groupByDate(events), ([date, items]) =>
      '<section aria-label="' + escapeHtml(dateLabel(date, false)) + '"><h3 class="list-day-heading">' + escapeHtml(dateLabel(date, false)) +
      '<span>' + items.length + '件</span></h3><div class="cards">' + items.map(cardHtml).join('') + '</div></section>').join('');
  }
  function render(forceDate) {
    const events = filteredEvents();
    chooseDate(events, forceDate);
    document.querySelectorAll('[data-view]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.view === state.view)));
    el('calendar-view').hidden = state.view !== 'calendar';
    el('list-view').hidden = state.view !== 'list';
    el('calendar-detail').hidden = state.view !== 'calendar';
    el('period-count').textContent = '条件に一致 ' + events.length + '件';
    const bounds = periodBounds();
    el('period-title').textContent = state.period === 'month' ?
      Number(state.month.slice(0, 4)) + '年' + Number(state.month.slice(5)) + '月' :
      shortDate(bounds.from) + '・' + shortDate(bounds.to);
    el('calendar-content').innerHTML = state.period === 'month' ? monthHtml(events) : weekendHtml(events);
    el('calendar-key').hidden = state.period !== 'month' || state.view !== 'calendar';
    el('selected-day-title').textContent = dateLabel(state.selectedDate, false);
    const selected = events.filter(event => event.event_date === state.selectedDate);
    el('selected-day-count').textContent = selected.length + '件';
    el('day-results').innerHTML = state.view === 'calendar' ? (selected.length ? '<div class="cards">' + selected.map(cardHtml).join('') + '</div>' : emptyHtml(true)) : '';
    el('list-results').innerHTML = state.view === 'list' ? renderList(events) : '';
    el('list-period-title').textContent = state.period === 'month' ?
      Number(state.month.slice(5)) + '月の掲載予定' : dateLabel(bounds.from, false) + '・' + dateLabel(bounds.to, false);
    el('list-period-count').textContent = events.length + '件';
    el('previous-period').disabled = state.period === 'month' ? state.month <= today.slice(0, 7) : state.weekend.from <= C.weekendOf(today).from;
    el('previous-period').setAttribute('aria-label', state.period === 'month' ? '前の月' : '前の週末');
    el('next-period').setAttribute('aria-label', state.period === 'month' ? '次の月' : '次の週末');
    const thisWeekend = C.weekendOf(today);
    document.querySelectorAll('[data-period]').forEach(button => {
      const value = button.dataset.period;
      const active = value === 'month' ? state.period === 'month' :
        value === 'this-weekend' ? state.period === 'weekend' && state.weekend.from === thisWeekend.from :
        state.period === 'weekend' && state.weekend.from === C.addDays(thisWeekend.from, 7);
      button.setAttribute('aria-pressed', String(active));
    });
    const conditions = [state.prefecture, state.category !== 'all' ? (state.category === 'keiko' ? '稽古会' : '錬成会・練習試合') : '',
      state.participation ? C.PARTICIPATION[state.participation] : '', state.organization ? '団体指定' : '', state.keyword ? 'キーワード指定' : ''].filter(Boolean);
    el('filter-summary').textContent = conditions.length ? conditions.join('／') : '参加対象や申込方法は公式案内をご確認ください。';
    el('result-announcement').textContent = (state.scope === 'tokyo' ? '東京都' : '関東') + '、' + (state.view === 'calendar' ? 'カレンダー表示' : '一覧表示') + '、条件に一致する掲載情報' + events.length + '件。';
  }
  function readFilters() {
    state.prefecture = state.scope === 'tokyo' ? '' : el('filter-prefecture').value;
    state.category = el('filter-category').value;
    state.participation = el('filter-participation').value;
    state.organization = el('filter-organization').value;
    state.keyword = el('filter-keyword').value;
    state.focusEvent = '';
    render(false);
  }
  function resetFilters() {
    state.prefecture = ''; state.category = 'all'; state.participation = ''; state.organization = ''; state.keyword = ''; state.focusEvent = '';
    el('filter-category').value = 'all'; el('filter-participation').value = ''; el('filter-keyword').value = '';
    updateOptions(); render(true);
  }
  function track(name, extra) {
    if (typeof window.gtag !== 'function') return;
    try {
      window.gtag('event', name, Object.assign({area_page: state.scope, view_mode: state.view, period_mode: state.period}, extra || {}));
    } catch (_) { /* Analytics must not interrupt searching. */ }
  }
  function periodKey() {
    const bounds = periodBounds();
    return state.period + ':' + bounds.from + ':' + bounds.to;
  }
  document.addEventListener('click', function (event) {
    const officialLink = event.target.closest('.card a');
    if (officialLink) {
      const card = officialLink.closest('.card');
      const item = payload.events.find(candidate => String(candidate.event_id) === card.dataset.eventId);
      if (item) track('event_source_click', {event_type: Object.hasOwn(payload.typeLabels, item.event_type) ? item.event_type : 'unknown'});
      return;
    }
    const button = event.target.closest('button');
    if (!button || button.disabled) return;
    if (button.dataset.view) {
      if (state.view === button.dataset.view) return;
      state.view = button.dataset.view;
      render(false); track('schedule_view_change');
    } else if (button.dataset.period) {
      const before = periodKey();
      state.focusEvent = '';
      if (button.dataset.period === 'month') {
        if (state.period === 'weekend') state.month = state.selectedDate.slice(0, 7);
        state.period = 'month';
      }
      else {
        state.period = 'weekend'; state.weekend = C.weekendOf(today);
        if (button.dataset.period === 'next-weekend') state.weekend = {from: C.addDays(state.weekend.from, 7), to: C.addDays(state.weekend.to, 7)};
      }
      render(true);
      if (before !== periodKey()) track('schedule_period_change');
    } else if (button.dataset.date) {
      const before = state.selectedDate;
      state.selectedDate = button.dataset.date; state.focusEvent = ''; render(false);
      if (before !== state.selectedDate) track('schedule_day_select');
      const replacement = Array.from(el('calendar-content').querySelectorAll('button[data-date]')).find(item => item.dataset.date === state.selectedDate);
      if (replacement) replacement.focus();
    } else if (button.dataset.event) {
      const selected = payload.events.find(item => item.event_id === button.dataset.event);
      if (selected) {
        const before = state.selectedDate;
        state.selectedDate = selected.event_date; state.focusEvent = selected.event_id; render(false);
        if (before !== state.selectedDate) track('schedule_day_select');
        const card = el('event-' + selected.event_id);
        if (card) {
          card.scrollIntoView({block: 'nearest', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
          card.focus({preventScroll: true});
        }
      }
    } else if (button.dataset.action === 'previous' || button.dataset.action === 'next') {
      const step = button.dataset.action === 'next' ? 1 : -1;
      state.focusEvent = '';
      if (state.period === 'month') state.month = C.addMonths(state.month, step);
      else state.weekend = {from: C.addDays(state.weekend.from, step * 7), to: C.addDays(state.weekend.to, step * 7)};
      render(true); track('schedule_period_change');
    } else if (button.dataset.action === 'current-month') {
      const before = periodKey();
      state.period = 'month'; state.month = today.slice(0, 7); state.focusEvent = ''; render(true);
      if (before !== periodKey()) track('schedule_period_change');
    } else if (button.dataset.action === 'reset-filters') resetFilters();
  });
  el('calendar-content').addEventListener('keydown', function (event) {
    if (state.period !== 'month' || !event.target.matches('button[data-date]')) return;
    const offset = {ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7}[event.key];
    if (offset === undefined) return;
    const current = event.target.dataset.date;
    const wanted = C.addDays(current, offset);
    const target = Array.from(el('calendar-content').querySelectorAll('button[data-date]')).find(button => button.dataset.date === wanted && !button.disabled);
    if (target) {event.preventDefault(); target.focus();}
  });
  ['filter-prefecture', 'filter-category', 'filter-participation', 'filter-organization'].forEach(id => el(id).addEventListener('change', readFilters));
  el('filter-keyword').addEventListener('input', readFilters);
  el('filter-participation').innerHTML = '<option value="">すべて</option>' + Object.entries(payload.participationLabels).map(([value, label]) =>
    '<option value="' + value + '">' + escapeHtml(label) + '</option>').join('');
  updateOptions(); updateRegion(); render(true);
  el('interactive-content').hidden = false;
  el('static-fallback').hidden = true;
})();
