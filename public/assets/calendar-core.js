(function (root) {
  'use strict';
  const PREFECTURES = ['東京都', '神奈川県', '埼玉県', '千葉県', '茨城県', '栃木県', '群馬県'];
  const CATEGORIES = {all: null, keiko: ['open_keiko', 'federation_keiko'], renseikai: ['adult_renseikai']};
  const PARTICIPATION = {
    anyone: '一般参加可', contact_required: '要事前連絡', registration_required: '要事前申込',
    invitation_required: '招待が必要', members_only: '会員・所属者限定', unknown: '参加条件未確認'
  };
  function iso(date) {return date.toISOString().slice(0, 10);}
  function parseDate(text) {
    if (typeof text !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(text)) return null;
    const date = new Date(text + 'T00:00:00Z');
    return Number.isFinite(date.getTime()) && iso(date) === text ? date : null;
  }
  function addDays(text, count) {
    const date = parseDate(text);
    if (!date || !Number.isInteger(count)) throw new Error('Invalid date arithmetic');
    date.setUTCDate(date.getUTCDate() + count);
    return iso(date);
  }
  function monthBounds(month) {
    if (typeof month !== 'string' || !/^\d{4}-\d{2}$/.test(month)) throw new Error('Invalid month');
    const first = parseDate(month + '-01');
    if (!first) throw new Error('Invalid month');
    const end = new Date(first.getTime());
    end.setUTCMonth(end.getUTCMonth() + 1, 0);
    return {from: iso(first), to: iso(end)};
  }
  function addMonths(month, count) {
    const date = parseDate(monthBounds(month).from);
    date.setUTCMonth(date.getUTCMonth() + count);
    return iso(date).slice(0, 7);
  }
  function monthDays(month) {
    const bounds = monthBounds(month);
    const weekday = parseDate(bounds.from).getUTCDay();
    const first = addDays(bounds.from, -((weekday + 6) % 7));
    const length = Math.ceil((((weekday + 6) % 7) + Number(bounds.to.slice(-2))) / 7) * 7;
    return Array.from({length}, (_, i) => addDays(first, i));
  }
  function weekendOf(text) {
    const day = parseDate(text);
    if (!day) throw new Error('Invalid date');
    const weekday = day.getUTCDay();
    const from = addDays(text, weekday === 0 ? -1 : 6 - weekday);
    return {from, to: addDays(from, 1)};
  }
  function todayJst(now) {
    const parts = new Intl.DateTimeFormat('en', {timeZone: 'Asia/Tokyo', year: 'numeric', month: '2-digit', day: '2-digit'}).formatToParts(now || new Date());
    const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
    return values.year + '-' + values.month + '-' + values.day;
  }
  function prefecture(event) {
    if (typeof event.area !== 'string') return '';
    const area = event.area.normalize('NFKC').trim();
    const names = area.match(/東京都|北海道|(?:京都|大阪)府|[^\s、,・/／]+?県/g) || [];
    const matched = PREFECTURES.filter(name => area.startsWith(name));
    return matched.length === 1 && names.length === 1 && names[0] === matched[0] ? matched[0] : '';
  }
  function participationType(event) {
    const value = Object.hasOwn(PARTICIPATION, event.participation_type) ? event.participation_type : 'unknown';
    return value === 'registration_required' && event.application_required === false ? 'unknown' : value;
  }
  function compareEvents(a, b) {
    return (a.event_date || '').localeCompare(b.event_date || '') || (a.start_time || '').localeCompare(b.start_time || '') ||
      (a.organization_id || '').localeCompare(b.organization_id || '') || (a.event_id || '').localeCompare(b.event_id || '');
  }
  function filterEvents(events, options) {
    const o = options || {};
    const category = CATEGORIES[o.category || 'all'];
    if (category === undefined) throw new Error('Unknown category');
    const words = (o.keyword || '').normalize('NFKC').trim().toLocaleLowerCase('ja').split(/\s+/).filter(Boolean);
    return events.filter(event => {
      if (event.status !== 'active' || !parseDate(event.event_date)) return false;
      const p = prefecture(event);
      if (!p || (o.scope === 'tokyo' && p !== '東京都')) return false;
      if (o.prefecture && p !== o.prefecture) return false;
      if (o.today && event.event_date < o.today) return false;
      if (o.from && event.event_date < o.from) return false;
      if (o.to && event.event_date > o.to) return false;
      if (category !== null && !category.includes(event.event_type)) return false;
      if (o.participation && participationType(event) !== o.participation &&
          !(o.participation === 'registration_required' && event.application_required === true)) return false;
      if (o.organization && event.organization_id !== o.organization) return false;
      const haystack = [event.title, event.organization_name, event.venue, event.area, event.raw_note].filter(Boolean).join(' ').normalize('NFKC').toLocaleLowerCase('ja');
      return words.every(word => haystack.includes(word));
    }).slice().sort(compareEvents);
  }
  function groupByDate(events) {
    const result = new Map();
    for (const event of events) {
      if (!result.has(event.event_date)) result.set(event.event_date, []);
      result.get(event.event_date).push(event);
    }
    return result;
  }
  function visibleDaySummary(events, limit) {
    const count = Math.max(0, Number.isInteger(limit) ? limit : 2);
    const ordered = events.slice().sort(compareEvents);
    return {total: ordered.length, shown: ordered.slice(0, count), remaining: Math.max(0, ordered.length - count)};
  }
  const api = {PREFECTURES, CATEGORIES, PARTICIPATION, parseDate, addDays, monthBounds, addMonths, monthDays, weekendOf,
    todayJst, prefecture, participationType, compareEvents, filterEvents, groupByDate, visibleDaySummary};
  root.KendoCalendarCore = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
})(typeof globalThis === 'object' ? globalThis : this);
