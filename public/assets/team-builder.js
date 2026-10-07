(() => {
      const root = document.getElementById('keiko-team-balance');
      const countInput = root.querySelector('#kb-count');
      const danCheck = root.querySelector('#kb-use-dan');
      const ageCheck = root.querySelector('#kb-use-age');
      const rosterElement = root.querySelector('#kb-roster');
      const rosterSummary = root.querySelector('#kb-roster-summary');
      const generate = root.querySelector('#kb-generate');
      const error = root.querySelector('#kb-error');
      const status = root.querySelector('#kb-status');
      const results = root.querySelector('#kb-results');
      const division = root.querySelector('#kb-division');
      const board = root.querySelector('#kb-board');
      const manual = root.querySelector('#kb-manual');
      const swapA = root.querySelector('#kb-swap-a');
      const swapB = root.querySelector('#kb-swap-b');
      const swapStatus = root.querySelector('#kb-swap-status');
      const printButton = root.querySelector('#kb-print');
      const ages = [21, 25, 28, 32, 35, 39, 42, 46, 50, 55, 60, 65];
      const dans = [1, 2, 3, 4, 3, 5, 4, 6, 5, 4, 6, 7];
      let players = ages.map((age, i) => ({id: i + 1, name: '選手' + String.fromCharCode(65 + i), age, dan: dans[i]}));
      let nextId = 13;
      let teams = [];
      let sample = true;
      let dirty = false;
      let beforeUnloadAttached = false;

      function beforeUnload(event) {
        event.preventDefault();
        event.returnValue = '';
      }
      function setDirty(value) {
        dirty = value;
        if (dirty && !beforeUnloadAttached) {
          window.addEventListener('beforeunload', beforeUnload);
          beforeUnloadAttached = true;
        } else if (!dirty && beforeUnloadAttached) {
          window.removeEventListener('beforeunload', beforeUnload);
          beforeUnloadAttached = false;
        }
      }
      function markDirty() { setDirty(true); }

      function random01() {
        if (!globalThis.crypto || typeof globalThis.crypto.getRandomValues !== 'function') return Math.random();
        const b = new Uint32Array(1); globalThis.crypto.getRandomValues(b); return b[0] / 4294967296;
      }
      function shuffle(values, random) {
        const out = values.slice();
        for (let i = out.length - 1; i > 0; i--) {
          const j = Math.floor(random() * (i + 1));
          const tmp = out[i]; out[i] = out[j]; out[j] = tmp;
        }
        return out;
      }
      function validate(roster, count, conditions) {
        if (!roster.length) throw new Error('選手を登録してください。');
        if (!Number.isInteger(count) || count < 1 || count > roster.length) throw new Error('チーム数は1〜' + roster.length + 'の整数にしてください。');
        if (new Set(roster.map(p => p.id)).size !== roster.length) throw new Error('選手の識別情報が重複しています。');
        for (const p of roster) {
          if (!p.name.trim()) throw new Error('選手名を入力してください。');
          if (p.age != null && (!Number.isInteger(p.age) || p.age < 1 || p.age > 120)) throw new Error(p.name + 'の年齢は1〜120の整数で入力してください。');
          if (p.dan != null && (!Number.isInteger(p.dan) || p.dan < 0 || p.dan > 8)) throw new Error(p.name + 'の段位は0〜8の整数で入力してください。');
          if (conditions.age && p.age == null) throw new Error('年齢を条件に使うため、' + p.name + 'の年齢を入力してください。');
          if (conditions.dan && p.dan == null) throw new Error('段位を条件に使うため、' + p.name + 'の段位を入力してください。');
        }
      }
      function plan(roster, count, conditions, random = random01) {
        validate(roster, count, conditions);
        const n = roster.length;
        const keys = ['dan', 'age'].filter(key => conditions[key]);
        const dimensions = keys.map(key => {
          const mean = roster.reduce((s, p) => s + p[key], 0) / n;
          const sd = Math.sqrt(roster.reduce((s, p) => s + (p[key] - mean) ** 2, 0) / n);
          return {key, mean, sd};
        }).filter(d => d.sd > 1e-9);
        const vectors = roster.map(p => dimensions.map(d => (p[d.key] - d.mean) / d.sd));
        const sizes = Array.from({length: count}, (_, i) => Math.floor(n / count) + (i < n % count ? 1 : 0));
        const starts = dimensions.length ? (n <= 40 ? 16 : 8) : 1;
        let best = null;
        let bestScore = Infinity;
        function teamScore(sum, size) { return sum.reduce((s, v) => s + (v / size) ** 2, 0); }
        for (let run = 0; run < starts; run++) {
          const capacities = shuffle(sizes, random);
          const indices = shuffle(Array.from({length: n}, (_, i) => i), random);
          const assignment = Array(n);
          const sums = capacities.map(() => dimensions.map(() => 0));
          let pos = 0;
          capacities.forEach((capacity, g) => {
            for (let j = 0; j < capacity; j++) {
              const i = indices[pos++]; assignment[i] = g;
              vectors[i].forEach((v, d) => { sums[g][d] += v; });
            }
          });
          for (let step = 0; step < (n <= 40 ? 48 : 24) && dimensions.length; step++) {
            let deltaBest = -1e-10;
            let pair = null;
            for (let a = 0; a < n; a++) {
              for (let b = a + 1; b < n; b++) {
                const ga = assignment[a], gb = assignment[b];
                if (ga === gb) continue;
                let delta = 0;
                for (let d = 0; d < dimensions.length; d++) {
                  const sa = sums[ga][d], sb = sums[gb][d];
                  const diff = vectors[b][d] - vectors[a][d];
                  delta += ((sa + diff) / capacities[ga]) ** 2 - (sa / capacities[ga]) ** 2;
                  delta += ((sb - diff) / capacities[gb]) ** 2 - (sb / capacities[gb]) ** 2;
                }
                if (delta < deltaBest) { deltaBest = delta; pair = [a, b]; }
              }
            }
            if (!pair) break;
            const [a, b] = pair, ga = assignment[a], gb = assignment[b];
            for (let d = 0; d < dimensions.length; d++) {
              const diff = vectors[b][d] - vectors[a][d]; sums[ga][d] += diff; sums[gb][d] -= diff;
            }
            assignment[a] = gb; assignment[b] = ga;
          }
          const score = sums.reduce((s, sum, g) => s + teamScore(sum, capacities[g]), 0);
          if (score < bestScore - 1e-12) { bestScore = score; best = assignment.slice(); }
          if (bestScore < 1e-12) break;
        }
        return {teams: Array.from({length: count}, (_, g) => roster.filter((_, i) => best[i] === g)), score: bestScore};
      }
      function element(tag, className, text) {
        const el = document.createElement(tag);
        if (className) el.className = className;
        if (text != null) el.textContent = text;
        return el;
      }
      function clearResult(message) {
        teams = []; results.hidden = true; board.replaceChildren();
        error.hidden = true; error.textContent = '';
        status.textContent = message; generate.textContent = 'チームを作る';
        swapStatus.textContent = '';
        printButton.hidden = true;
      }
      function summary() {
        rosterSummary.textContent = '選手を登録・編集（' + (sample ? 'サンプル' : '') + players.length + '人）';
        countInput.max = String(Math.max(1, players.length));
      }
      function changedRoster() {
        sample = false;
        markDirty();
        summary();
        clearResult('選手情報を更新しました。編成し直してください。');
        if (!players.length) setDirty(false);
      }
      function renderRoster() {
        rosterElement.replaceChildren();
        players.forEach(p => {
          const row = element('div', 'kb-roster-row');
          row.dataset.playerId = String(p.id);
          ['name', 'age', 'dan'].forEach(key => {
            const input = element('input', 'kb-input');
            input.type = key === 'name' ? 'text' : 'number';
            input.value = p[key] == null ? '' : String(p[key]);
            input.id = 'kb-' + key + '-' + p.id;
            input.setAttribute('aria-label', '選手' + p.id + 'の' + ({name: '名前', age: '年齢', dan: '段位'})[key]);
            if (key !== 'name') {
              input.min = key === 'age' ? '1' : '0'; input.max = key === 'age' ? '120' : '8'; input.step = '1'; input.inputMode = 'numeric';
            }
            input.addEventListener('input', () => {
              p[key] = key === 'name' ? input.value : (input.value === '' ? null : Number(input.value));
              changedRoster();
            });
            row.append(input);
          });
          const remove = element('button', 'kb-secondary kb-remove', '×');
          remove.type = 'button'; remove.setAttribute('aria-label', '選手' + p.id + 'を削除');
          remove.addEventListener('click', () => {
            players = players.filter(player => player.id !== p.id); changedRoster(); renderRoster();
          });
          row.append(remove); rosterElement.append(row);
        });
        summary();
      }
      function average(team, key) {
        if (team.some(p => p[key] == null)) return null;
        return team.reduce((s, p) => s + p[key], 0) / team.length;
      }
      function renderTeams() {
        board.replaceChildren();
        const frequency = new Map();
        teams.forEach(team => frequency.set(team.length, (frequency.get(team.length) || 0) + 1));
        const sizes = [...frequency.entries()].sort((a, b) => b[0] - a[0]);
        division.textContent = players.length + '人 → ' + teams.length + 'チーム（' + sizes.map(([size, qty]) => size + '人×' + qty + 'チーム').join('・') + '）';
        teams.forEach((team, i) => {
          const card = element('section', 'kb-team');
          card.append(element('h3', '', 'チーム' + (i + 1) + ' · ' + team.length + '人'));
          const metrics = element('div', 'kb-metrics');
          const age = average(team, 'age'), dan = average(team, 'dan');
          metrics.append(element('span', 'kb-mean-age', '平均年齢 ' + (age == null ? '未入力あり' : age.toFixed(1) + '歳')));
          metrics.append(element('span', 'kb-mean-dan', '平均段位 ' + (dan == null ? '未入力あり' : dan.toFixed(1))));
          card.append(metrics);
          const list = element('ul', 'kb-members');
          team.forEach(p => {
            const li = element('li', 'kb-member'); li.dataset.playerId = String(p.id);
            li.append(element('span', 'kb-member-name', p.name));
            const ageText = p.age == null ? '年齢未入力' : p.age + '歳';
            const danText = p.dan == null ? '段位未入力' : (p.dan === 0 ? '段位なし' : p.dan + '段');
            li.append(element('span', 'kb-member-detail', ageText + ' · ' + danText));
            list.append(li);
          });
          card.append(list); board.append(card);
        });
        results.hidden = false; manual.hidden = teams.length < 2; printButton.hidden = false;
        populateSwaps();
      }
      function populateSwaps() {
        const previousA = swapA.value, previousB = swapB.value;
        swapA.replaceChildren(); swapB.replaceChildren();
        teams.forEach((team, i) => team.forEach(p => {
          [swapA, swapB].forEach(select => {
            const option = element('option', '', p.name + '（チーム' + (i + 1) + '）');
            option.value = String(p.id); select.append(option);
          });
        }));
        const ids = new Set(players.map(p => String(p.id)));
        swapA.value = ids.has(previousA) ? previousA : String(teams[0][0].id);
        swapB.value = ids.has(previousB) ? previousB : String((teams[1] || teams[0])[0].id);
      }
      function build() {
        try {
          const conditions = {age: ageCheck.checked, dan: danCheck.checked};
          const result = plan(players, Number(countInput.value), conditions);
          teams = result.teams;
          error.hidden = true; error.textContent = ''; swapStatus.textContent = '';
          renderTeams(); generate.textContent = 'もう一度編成する';
          const labels = [];
          if (conditions.dan) labels.push('段位'); if (conditions.age) labels.push('年齢');
          status.textContent = labels.length ? labels.join('・') + 'の平均値の偏りを抑えた編成案です。' : '人数をそろえたランダム編成です。';
        } catch (e) {
          clearResult('入力内容を確認してください。'); error.textContent = e.message; error.hidden = false;
        }
      }
      root.querySelector('#kb-add').addEventListener('click', () => {
        if (players.length >= 60) { error.textContent = 'この試作では60人まで登録できます。'; error.hidden = false; return; }
        const id = nextId++; players.push({id, name: '', age: null, dan: null});
        changedRoster(); renderRoster(); root.querySelector('#kb-editor').open = true;
        root.querySelector('#kb-name-' + id).focus();
      });
      root.querySelector('#kb-swap').addEventListener('click', () => {
        const a = Number(swapA.value), b = Number(swapB.value);
        const ga = teams.findIndex(team => team.some(p => p.id === a));
        const gb = teams.findIndex(team => team.some(p => p.id === b));
        if (ga < 0 || gb < 0 || ga === gb) { swapStatus.textContent = '別チームの2人を選んでください。'; return; }
        const ia = teams[ga].findIndex(p => p.id === a), ib = teams[gb].findIndex(p => p.id === b);
        const pa = teams[ga][ia], pb = teams[gb][ib];
        markDirty();
        teams[ga][ia] = pb; teams[gb][ib] = pa;
        renderTeams();
        swapStatus.textContent = pa.name + ' ↔ ' + pb.name + ' を入れ替えました。';
        status.textContent = '手動調整した編成案です。各チームの平均値を確認してください。';
      });
      printButton.addEventListener('click', () => window.print());
      generate.addEventListener('click', () => { markDirty(); build(); });
      countInput.addEventListener('change', () => { markDirty(); build(); });
      danCheck.addEventListener('change', () => { markDirty(); build(); });
      ageCheck.addEventListener('change', () => { markDirty(); build(); });
      renderRoster(); build();
      return {plan};
    })();
