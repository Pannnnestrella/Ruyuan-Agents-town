const ui = {
    landing: document.getElementById('landing'),
    game: document.getElementById('game'),
    create: document.getElementById('create-game'),
    premise: document.getElementById('scenario-premise'),
    title: document.getElementById('game-title'),
    round: document.getElementById('round-number'),
    maxRounds: document.getElementById('max-rounds'),
    actionStep: document.getElementById('director-action-step'),
    phase: document.getElementById('phase-label'),
    selectedCard: document.getElementById('selected-card-label'),
    planner: document.getElementById('planner-label'),
    gameId: document.getElementById('game-id-label'),
    locations: document.getElementById('locations'),
    timeline: document.getElementById('timeline'),
    notices: document.getElementById('notices'),
    noticeContent: document.getElementById('notice-content'),
    postNotice: document.getElementById('post-notice'),
    cards: document.getElementById('event-cards'),
    emptyEvent: document.getElementById('empty-event-option'),
    intelOptions: document.getElementById('intel-options'),
    intelHistory: document.getElementById('intel-history'),
    advance: document.getElementById('advance-round'),
    exportTimeline: document.getElementById('export-timeline'),
    viewRecap: document.getElementById('view-recap'),
    recapPanel: document.getElementById('recap-panel'),
    recapContent: document.getElementById('recap-content'),
    closeRecap: document.getElementById('close-recap'),
    actionHint: document.getElementById('action-hint'),
    hostRoundTitle: document.getElementById('host-round-title'),
    hostObjective: document.getElementById('host-objective'),
    hostReach: document.getElementById('host-reach'),
    hostPressure: document.getElementById('host-pressure'),
    hostInterventions: document.getElementById('host-interventions'),
    plannerProvider: document.getElementById('planner-provider'),
    plannerModel: document.getElementById('planner-model'),
    switchPlanner: document.getElementById('switch-planner'),
    casebook: document.getElementById('director-casebook'),
    casebookKiller: document.getElementById('casebook-killer'),
    murderChain: document.getElementById('murder-chain'),
    objectiveTimeline: document.getElementById('casebook-objective-timeline'),
    caseCore: document.getElementById('case-core'),
    objectiveTruths: document.getElementById('objective-truths'),
    clueMap: document.getElementById('director-clue-map'),
    deductionFoundation: document.getElementById('shared-deduction-foundation'),
    deductionGuides: document.getElementById('variant-deduction-guides'),
    characterFiles: document.getElementById('director-character-files'),
    dispatchLayer: document.getElementById('director-dispatch-layer'),
    hostNotifications: document.getElementById('host-notifications'),
    hostNotificationList: document.getElementById('host-notification-list'),
    clearHostNotifications: document.getElementById('clear-host-notifications'),
    toast: document.getElementById('toast'),
};

document.getElementById('director-new-game')?.addEventListener('click', () => {
    if (gameId) window.localStorage.removeItem(`interactiveLiveCursor:${gameId}`);
    window.localStorage.removeItem('interactiveGameId');
    window.location.reload();
});

window.addEventListener('storage', event => {
    if (event.key === 'interactiveGameId' && event.newValue !== gameId) {
        window.location.reload();
    }
});

let gameId = null;
let currentState = null;
let selectedCardId = null;
let availableCards = [];
let directorBusy = false;
let lastDirectorSyncKey = '';
let notificationCursor = 0;
let hostNotifications = [];
let directorMapGameId = null;
let directorMapEventCursor = 0;
let directorMapVisualLocations = {};
let directorMapInitialized = false;
let directorMapAnimating = false;
let directorMapPlayback = Promise.resolve();

const categoryLabels = {
    pressure: '压力事件',
    information: '信息事件',
    relationship: '关系事件',
    quiet: '空事件',
};

async function api(path, options = {}) {
    try {
        const response = await fetch(path, {
            headers: {'Content-Type': 'application/json', ...(options.headers || {})},
            ...options,
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || `请求失败（${response.status}）`);
        return data;
    } catch (error) {
        if (!path.startsWith('/api/interactive/host-notifications')) {
            pushLocalNotification(error, path);
        }
        throw error;
    }
}

function escapeHtml(value) {
    return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
}

const earthlyBranchStartHours = {
    子: 23, 丑: 1, 寅: 3, 卯: 5, 辰: 7, 巳: 9,
    午: 11, 未: 13, 申: 15, 酉: 17, 戌: 19, 亥: 21,
};

function formatTimelineTime(value) {
    const text = String(value ?? '');
    return text.replace(/([子丑寅卯辰巳午未申酉戌亥])(初|正)([一二三四]?刻)?|([子丑寅卯辰巳午未申酉戌亥])末/g,
        (match, branch, phase, quarter, endBranch) => {
            const activeBranch = branch || endBranch;
            let minutes = earthlyBranchStartHours[activeBranch] * 60;
            if (endBranch) {
                minutes += 105;
            } else {
                if (phase === '正') minutes += 60;
                const quarterCount = {'一刻': 1, '二刻': 2, '三刻': 3, '四刻': 4}[quarter] || 0;
                minutes += quarterCount * 15;
            }
            minutes %= 24 * 60;
            const hours = String(Math.floor(minutes / 60)).padStart(2, '0');
            const mins = String(minutes % 60).padStart(2, '0');
            return `${match}(${hours}:${mins})`;
        });
}

function showToast(message) {
    ui.toast.textContent = message;
    ui.toast.classList.remove('hidden');
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => ui.toast.classList.add('hidden'), 3200);
}

function renderHostNotifications() {
    if (!ui.hostNotifications || !ui.hostNotificationList) return;
    ui.hostNotifications.classList.toggle('hidden', hostNotifications.length === 0);
    ui.hostNotificationList.innerHTML = hostNotifications.slice().reverse().map(item => `
        <article class="host-notification ${item.kind === 'rate_limit' ? 'rate-limit' : ''}">
            <div><strong>${escapeHtml(item.title || '系统异常')}</strong><time>${escapeHtml(item.created_at || '')}</time></div>
            <p>${escapeHtml(item.message || '未知异常')}</p>
            <small>${escapeHtml(item.provider || item.source || 'browser')}${item.status_code ? ` · HTTP ${escapeHtml(item.status_code)}` : ''}${item.count > 1 ? ` · 重复 ${item.count} 次` : ''}</small>
        </article>
    `).join('');
}

function pushLocalNotification(error, source = 'browser') {
    const message = error?.message || String(error);
    hostNotifications.push({
        id: `browser-${Date.now()}-${hostNotifications.length}`,
        kind: message.includes('429') ? 'rate_limit' : 'exception',
        title: message.includes('429') ? '模型接口限流（HTTP 429）' : '浏览器请求异常',
        message,
        source,
        created_at: new Date().toLocaleString(),
        count: 1,
    });
    hostNotifications = hostNotifications.slice(-100);
    renderHostNotifications();
}

async function pollHostNotifications() {
    try {
        const response = await fetch(`/api/interactive/host-notifications?after=${notificationCursor}`);
        if (!response.ok) return;
        const data = await response.json();
        const incoming = data.notifications || [];
        if (!incoming.length) return;
        notificationCursor = Math.max(notificationCursor, ...incoming.map(item => Number(item.id) || 0));
        hostNotifications.push(...incoming);
        hostNotifications = hostNotifications.slice(-100);
        renderHostNotifications();
        showToast(incoming[incoming.length - 1].title || '主持台收到一条异常通知');
    } catch {
        // The notification channel must not create recursive notifications.
    }
}

ui.clearHostNotifications?.addEventListener('click', async () => {
    hostNotifications = [];
    renderHostNotifications();
    try {
        await api('/api/interactive/host-notifications', {method: 'DELETE'});
        notificationCursor = 0;
    } catch {
        // The local list is already cleared; a later poll can restore anything
        // that could not be removed from the server.
    }
});

window.addEventListener('error', event => {
    pushLocalNotification(event.error || new Error(event.message), 'window.error');
});
window.addEventListener('unhandledrejection', event => {
    pushLocalNotification(
        event.reason instanceof Error ? event.reason : new Error(String(event.reason)),
        'unhandledrejection',
    );
});

function showDirectorDispatch(kind, data) {
    if (!ui.dispatchLayer) return;
    ui.dispatchLayer.replaceChildren();
    const isIntel = kind === 'intel';
    const card = document.createElement('article');
    card.className = `dispatch-card ${isIntel ? 'yuan-report' : 'world-card'}`;
    const reliability = isIntel && data.reliability != null
        ? ` · 可信度 ${Math.round(Number(data.reliability) * 100)}%`
        : '';
    card.innerHTML = `
        <button class="dispatch-close" type="button" aria-label="收起">×</button>
        <span class="dispatch-kicker">${isIntel ? '鸢报 · 全局公开情报' : escapeHtml(categoryLabels[data.category] || '局势事件')}</span>
        <h2>${escapeHtml(data.title || '无题情报')}</h2>
        <p>${escapeHtml(data.claim || data.description || '')}</p>
        <footer>${escapeHtml(isIntel ? `${data.source || '来源不明'}${reliability}` : data.impact_preview || '局势已经写入世界')}</footer>`;
    ui.dispatchLayer.appendChild(card);
    requestAnimationFrame(() => card.classList.add('shown'));
    const dismiss = () => {
        card.classList.remove('shown');
        window.setTimeout(() => card.remove(), 360);
    };
    card.querySelector('.dispatch-close').addEventListener('click', dismiss);
    window.setTimeout(dismiss, 6800);
}

function delay(milliseconds) {
    return new Promise(resolve => window.setTimeout(resolve, milliseconds));
}

async function waitForRoundTask(taskId) {
    for (let attempt = 0; attempt < 240; attempt += 1) {
        const task = await api(`/api/interactive/tasks/${taskId}`);
        ui.actionHint.textContent = task.message || '正在推演……';
        if (task.status === 'succeeded') return task.result;
        if (task.status === 'failed') throw new Error(task.error || '本轮推演失败');
        await delay(750);
    }
    throw new Error('本轮推演等待超时，请刷新页面检查存档状态。');
}

function setBusy(busy, message = '') {
    directorBusy = busy;
    ui.create.disabled = busy;
    ui.postNotice.disabled = busy || !currentState || !['intervention', 'ready'].includes(currentState.phase);
    ui.advance.disabled = busy || !selectedCardId || currentState?.phase !== 'ready' || currentState?.player_controlled;
    ui.intelOptions?.querySelectorAll('button').forEach(button => {
        button.disabled = busy || !currentState || !['intervention', 'ready'].includes(currentState.phase);
    });
    if (message) ui.actionHint.textContent = message;
}

function directorSyncKey(state) {
    return JSON.stringify({
        round: state?.round_number,
        step: state?.action_step,
        phase: state?.phase,
        card: state?.active_event_card,
        intel: state?.active_public_intel,
        events: state?.events?.length,
        notices: state?.notices?.length,
    });
}

function renderDirectorMap(state) {
    if (!state || !ui.locations) return;
    if (directorMapAnimating) return;
    window.InteractiveMap.render(ui.locations, state, {visualLocations: directorMapVisualLocations});
}

async function animateDirectorMapMove(event) {
    const actorId = event.actors?.[0];
    const destination = event.payload?.destination_id || event.state_changes?.find(change => change.agent_id === actorId)?.location_id;
    const token = ui.locations.querySelector(`[data-agent-id="${CSS.escape(actorId || '')}"]`);
    const destinationLayer = ui.locations.querySelector(`[data-location-id="${CSS.escape(destination || '')}"] .token-layer`);
    if (!token || !destinationLayer) return;
    const before = token.getBoundingClientRect();
    destinationLayer.appendChild(token);
    const after = token.getBoundingClientRect();
    directorMapVisualLocations[actorId] = destination;
    await token.animate([
        {transform: `translate(${before.left - after.left}px, ${before.top - after.top}px)`, zIndex: 30},
        {transform: 'translate(0, 0)', zIndex: 30},
    ], {duration: 780, easing: 'cubic-bezier(.2,.78,.25,1)'}).finished.catch(() => {});
}

function syncDirectorMap(state) {
    if (!state) return;
    if (directorMapGameId !== state.game_id) {
        directorMapGameId = state.game_id;
        directorMapEventCursor = (state.events || []).length;
        directorMapVisualLocations = Object.fromEntries(Object.values(state.agents || {}).map(agent => [agent.agent_id, agent.location_id]));
        directorMapInitialized = false;
        directorMapAnimating = false;
    }
    if (!directorMapInitialized) {
        directorMapInitialized = true;
        renderDirectorMap(state);
        return;
    }
    const events = state.events || [];
    const moves = events.slice(directorMapEventCursor).filter(event => event.event_type === 'move');
    directorMapEventCursor = events.length;
    if (!moves.length || directorMapAnimating) return;
    directorMapAnimating = true;
    directorMapPlayback = directorMapPlayback.then(async () => {
        for (const event of moves) await animateDirectorMapMove(event);
        Object.values(state.agents || {}).forEach(agent => { directorMapVisualLocations[agent.agent_id] = agent.location_id; });
        directorMapAnimating = false;
        renderDirectorMap(state);
    }).catch(() => { directorMapAnimating = false; renderDirectorMap(state); });
}

async function pollDirectorState() {
    if (!gameId || directorBusy) return;
    try {
        const [data, observer] = await Promise.all([
            api(`/api/interactive/games/${gameId}/director`),
            api(`/api/interactive/games/${gameId}/observer`),
        ]);
        const key = directorSyncKey(data.state);
        if (key === lastDirectorSyncKey) return;
        lastDirectorSyncKey = key;
        renderState(data.state, observer.state);
        syncDirectorMap(observer.state);
        renderCards(data.cards || [], data.empty_event, data.state.active_event_card);
        renderIntel(data.intel || [], data.state);
        if (
            data.state.player_controlled
            && data.state.phase === 'intervention'
            && !data.state.active_event_card
        ) {
            ui.actionHint.textContent = '角色席已结束上一轮。现在可以选择下一张事件卡；按钮已经重新启用。';
        }
    } catch (error) {
        // A transient poll failure should not replace the director's current controls.
    }
}

function renderState(state, mapState = state) {
    currentState = state;
    ui.title.textContent = state.title;
    ui.round.textContent = state.round_number;
    ui.maxRounds.textContent = state.max_rounds;
    ui.actionStep.textContent = `${state.action_step || 0}/${state.actions_per_round || 3}`;
    ui.gameId.textContent = `局号：${state.game_id}`;
    ui.planner.textContent = state.planner === 'LLMIntentPlanner'
        ? state.planner_runtime?.is_falling_back
            ? `${plannerLabel(state.planner_provider)} 不可用 · 当前为本地兜底`
            : `LLM 并行决策 · ${plannerLabel(state.planner_provider)}`
        : '本地规则决策';
    ui.phase.textContent = state.phase === 'finished'
        ? '推演已经结束'
        : state.phase === 'voting'
            ? '等待玩家角色完成终局投票'
            : state.player_controlled && ['ready', 'player_turn'].includes(state.phase)
                ? '等待玩家角色决定下一次行动'
                : '等待主持人干预';
    ui.selectedCard.textContent = state.active_event_card ? `已选择：${state.active_event_card}` : '尚未选择事件卡';

    const latestNotice = state.notices[state.notices.length - 1];
    const injured = Object.values(state.agents).filter(agent => agent.life_state !== 'alive').length;
    const interventionCount = (state.notices?.length || 0)
        + (state.public_intel_history?.length || 0)
        + state.events.filter(event => event.event_type === 'event_card_selected').length;
    const pressure = injured ? '失控边缘' : state.round_number >= 5 ? '终局逼近' : state.round_number >= 2 ? '秘密发酵' : '彼此试探';
    ui.hostRoundTitle.textContent = `你正在主持第 ${Math.min(state.round_number + 1, state.max_rounds)} 轮`;
    ui.hostReach.textContent = `最近公告触达 ${latestNotice?.seen_by?.length || 0}/6`;
    ui.hostPressure.textContent = `局势：${pressure}`;
    ui.hostInterventions.textContent = `已干预 ${interventionCount} 次`;
    ui.hostObjective.textContent = state.phase === 'finished'
        ? '推演已经闭合，可以从复盘中检查你的干预如何改变人物路线。'
        : state.active_event_card
            ? '局势已经就绪。推进回合后，观察谁坚持原计划、谁被迫转向。'
            : state.round_number >= 5
                ? '终局将近：选择迫使角色表态的事件，同时避免直接替他们给出答案。'
                : '选择你希望放大的矛盾：时间压力、新线索，或人物之间的公开对质。';

    renderDirectorMap(mapState);

    const events = [...state.events].reverse();
    ui.timeline.innerHTML = events.length ? events.map(event => `
        <article class="timeline-item ${escapeHtml(event.event_type)}">
            <div>${escapeHtml(event.summary)}</div>
            <div class="timeline-meta">第 ${event.round_number} 轮${event.action_step ? ` · 行动 ${event.action_step}` : ''} · ${escapeHtml(event.event_type)}</div>
        </article>
    `).join('') : '<p class="timeline-meta">尚无公开事件。选择事件卡并推进第一轮后，局势会从这里展开。</p>';

    ui.notices.innerHTML = state.notices.map(notice => `
        <span class="notice-pill">第 ${notice.round_number} 轮 · ${escapeHtml(notice.content)}（触达 ${notice.seen_by.length}/6）</span>
    `).join('');
    ui.intelHistory.innerHTML = (state.public_intel_history || []).map(intel => `
        <span class="notice-pill">第 ${intel.round_number} 轮 · ${escapeHtml(intel.title)}（全员）</span>
    `).join('');

    if (state.director_casebook) renderDirectorCasebook(state);

    if (state.phase === 'finished') {
        ui.advance.disabled = true;
        ui.advance.classList.add('hidden');
        ui.viewRecap?.classList.remove('hidden');
        ui.postNotice.disabled = true;
        ui.actionHint.textContent = '六轮十八次行动已经结束，终局真相与事件证据已经整理完成。';
    } else {
        ui.advance.classList.remove('hidden');
        ui.viewRecap?.classList.add('hidden');
        if (state.player_controlled && ['ready', 'player_turn'].includes(state.phase)) {
            ui.actionHint.textContent = `角色席正在决定第 ${Math.min(state.round_number + 1, state.max_rounds)} 轮行动 ${(state.action_step || 0) + 1}/${state.actions_per_round || 3}。`;
        }
    }
}

function renderDirectorCasebook(state) {
    const casebook = state.director_casebook;
    if (!casebook || !ui.casebook) return;
    ui.casebook.classList.remove('hidden');
    ui.casebookKiller.textContent = `本局凶手 · ${casebook.killer_name}`;

    ui.murderChain.innerHTML = (casebook.murder_chain || []).map((item, index) => `
        <article class="murder-step">
            <span>${String(index + 1).padStart(2, '0')} · ${escapeHtml(item.stage)}</span>
            <div><strong>${escapeHtml(item.title)}</strong><p>${escapeHtml(item.detail || '本环节没有额外记录。')}</p></div>
        </article>
    `).join('');

    const weapon = casebook.weapon?.name || '未知凶器';
    const stolen = casebook.stolen_item?.name || '未知关键物';
    const evidence = (casebook.evidence || []).map(item => item.name).join('、') || '尚无专属痕迹';
    ui.caseCore.innerHTML = `
        <dt>真实凶手</dt><dd class="danger-text">${escapeHtml(casebook.killer_name)}</dd>
        <dt>作案动机</dt><dd>${escapeHtml(casebook.motive)}</dd>
        <dt>作案手段</dt><dd>${escapeHtml(casebook.method)}</dd>
        <dt>凶器</dt><dd>${escapeHtml(weapon)}</dd>
        <dt>取走物</dt><dd>${escapeHtml(stolen)}</dd>
        <dt>遗留痕迹</dt><dd>${escapeHtml(evidence)}</dd>
        <dt>掩护计划</dt><dd>${escapeHtml(casebook.cover_plan)}</dd>`;
    ui.objectiveTruths.innerHTML = (casebook.objective_truths || [])
        .map(truth => `<li>${escapeHtml(truth.claim)}</li>`).join('');
    ui.objectiveTimeline.innerHTML = (casebook.objective_timeline || []).map(entry => `
        <article class="${entry.private ? 'private' : ''}">
            <time>${escapeHtml(formatTimelineTime(entry.time))}</time>
            <div><strong>${escapeHtml(entry.location_name || '')}</strong><p>${escapeHtml(entry.text)}</p>
            <small>${escapeHtml((entry.participants || []).join('、'))}${entry.private ? ' · 凶手私密记忆' : ''}</small></div>
        </article>`).join('');
    renderDirectorClueMap(casebook, state);
    renderDeductionGuides(casebook);

    ui.characterFiles.innerHTML = (casebook.characters || []).map(character => {
        const current = character.current_state || {};
        const location = state.locations[current.location_id]?.name || current.location_id || '未知';
        const portrait = `/static/assets/village/agents/${encodeURIComponent(character.display_name)}/portrait.png`;
        const secrets = character.secrets || [];
        const beliefs = current.beliefs || [];
        const inventory = character.inventory_objects || [];
        const actions = character.actions || [];
        const plan = current.strategic_plan || {};
        return `
            <details class="director-character-file ${character.is_killer ? 'killer-file' : ''}">
                <summary>
                    <img src="${portrait}" alt="${escapeHtml(character.display_name)}立绘" onerror="this.style.display='none'">
                    <div><strong>${escapeHtml(character.display_name)}</strong><span>${escapeHtml(character.public_role)}</span></div>
                    ${character.is_killer ? '<b class="killer-tag">真实凶手</b>' : '<b>密探档案</b>'}
                    <small>${escapeHtml(location)} · ${escapeHtml(lifeLabel(current.life_state))} · ${beliefs.length} 条记忆</small>
                </summary>
                <div class="character-file-body">
                    <section class="file-block full"><h4>人物背景</h4>
                        ${character.opening_hook ? `<blockquote>${escapeHtml(character.opening_hook)}</blockquote>` : ''}
                        ${(character.background_story || []).map(text => `<p>${escapeHtml(text)}</p>`).join('') || '<p>未记录。</p>'}
                    </section>
                    <section class="file-block full"><h4>案发前个人时间线</h4><ol class="pregame-ledger">${(character.pregame_timeline || []).map(entry => `
                        <li class="${entry.private ? 'private' : ''}"><time>${escapeHtml(formatTimelineTime(entry.time))}</time><span>${escapeHtml(entry.text)}</span><small>${escapeHtml(entry.location_name || '')}</small></li>
                    `).join('') || '<li>未记录。</li>'}</ol></section>
                    ${renderFileList('初始记忆', character.background_memories)}
                    ${renderFileList('个人目标', character.goals)}
                    ${renderFileList('决策准则', character.decision_rules)}
                    <section class="file-block secret-block"><h4>所有秘密</h4><ul>${secrets.length ? secrets.map(secret => `
                        <li><strong>${escapeHtml(secret.title)}</strong><span>${escapeHtml(secret.claim)}</span><small>分类：${escapeHtml(secret.category)} · 已暴露给 ${secret.exposed_to?.length || 0} 人</small></li>
                    `).join('') : '<li>无登记秘密。</li>'}</ul></section>
                    <section class="file-block"><h4>当前持有物</h4><ul>${inventory.length ? inventory.map(item => `
                        <li><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.metadata?.description || '')}</span><small>${item.hidden ? '隐藏持有' : '公开持有'}</small></li>
                    `).join('') : '<li>没有物品。</li>'}</ul></section>
                    <section class="file-block full"><h4>完整记忆与情报</h4><div class="belief-ledger">${beliefs.length ? beliefs.map(belief => `
                        <article><p>${escapeHtml(belief.claim)}</p><small>来源：${escapeHtml(belief.source)} · 可信度 ${Math.round(Number(belief.confidence || 0) * 100)}% · 第 ${belief.learned_round} 轮${belief.shared_with?.length ? ` · 已分享给 ${belief.shared_with.map(id => escapeHtml(state.agents[id]?.display_name || id)).join('、')}` : ''}</small></article>
                    `).join('') : '<p>尚无记忆。</p>'}</div></section>
                    <section class="file-block"><h4>当前跨回合计划</h4>${renderPlan(plan)}</section>
                    <section class="file-block"><h4>状态与得分</h4><p>${escapeHtml(lifeLabel(current.life_state))} · ${escapeHtml((current.conditions || []).join('、') || '无异常状态')} · 得分 ${current.score || 0}</p><p>已发现他人秘密 ${(current.discovered_secret_ids || []).length} 项。</p></section>
                    <section class="file-block full"><h4>本局行动与发言</h4><ol class="action-ledger">${actions.length ? actions.map(event => `
                        <li><span>第 ${event.round_number} 轮${event.action_step ? ` / 行动 ${event.action_step}` : ''}</span>${escapeHtml(event.summary)}<small>${event.public ? '公开' : '隐藏'} · ${escapeHtml(event.event_type)}</small></li>
                    `).join('') : '<li>尚未行动。</li>'}</ol></section>
                </div>
            </details>`;
    }).join('');
}

function renderDirectorClueMap(casebook, state) {
    if (!ui.clueMap) return;
    const clues = casebook.clue_map || [];
    const groups = new Map();
    clues.forEach(clue => {
        if (!groups.has(clue.current_group)) groups.set(clue.current_group, {
            label: clue.current_where,
            clues: [],
        });
        groups.get(clue.current_group).clues.push(clue);
    });
    const kindLabels = {
        truth: '真相拼图', evidence: '案件物证', secret: '人物秘密',
        decoy: '混淆项', personal: '随身信息', variant: '变体专属',
    };
    const healthColumn = `<article class="clue-location-group health-location-group">
        <header><h4>人物健康</h4><span>${Object.keys(state.agents || {}).length} 人</span></header>
        <div class="health-roster">${Object.values(state.agents || {}).map(agent => {
            const conditions = Array.isArray(agent.conditions)
                ? agent.conditions.join('、')
                : agent.conditions || '无异常状态';
            return `<div class="health-roster-item">
                <strong>${escapeHtml(agent.display_name)}</strong>
                <span class="health-state health-${escapeHtml(agent.life_state || 'alive')}">${escapeHtml(lifeLabel(agent.life_state || 'alive'))}</span>
                <small>${escapeHtml(conditions)}</small>
            </div>`;
        }).join('')}</div>
    </article>`;
    ui.clueMap.innerHTML = healthColumn + [...groups.values()].map(group => `
        <article class="clue-location-group">
            <header><h4>${escapeHtml(group.label)}</h4><span>${group.clues.length} 项</span></header>
            <div>${group.clues.sort((a, b) => Number(b.hidden) - Number(a.hidden)).map(clue => {
                const visualKind = clue.is_case_variant ? 'variant' : clue.kind;
                const discovered = clue.discovered_by?.length
                    ? `已被 ${clue.discovered_by.map(escapeHtml).join('、')} 发现`
                    : '尚无人发现';
                return `<details class="clue-card kind-${escapeHtml(visualKind)}">
                    <summary><strong>${escapeHtml(clue.name)}</strong><span>${escapeHtml(kindLabels[visualKind] || visualKind)}${clue.hidden ? ' · 隐藏' : ''}</span></summary>
                    <p>${escapeHtml(clue.claim)}</p>
                    ${clue.truth_claim ? `<blockquote>可拼向：${escapeHtml(clue.truth_claim)}</blockquote>` : ''}
                    <small>${escapeHtml(discovered)} · ${clue.searchable ? '可在此处搜查发现' : '需要持有者出示、交付或被对质'}${clue.initial_where !== clue.current_where ? ` · 原始布置：${escapeHtml(clue.initial_where)}` : ''}</small>
                </details>`;
            }).join('')}</div>
        </article>
    `).join('');
}

function renderDeductionGuides(casebook) {
    if (!ui.deductionFoundation || !ui.deductionGuides) return;
    const references = casebook.reference_index || {};
    ui.deductionFoundation.innerHTML = (casebook.shared_deduction_foundation || [])
        .map((item, index) => renderDeductionStep(item, index, references)).join('');
    const guides = [...(casebook.variant_guides || [])].sort((a, b) => Number(b.active) - Number(a.active));
    ui.deductionGuides.innerHTML = guides.map(guide => `
        <details class="variant-guide ${guide.active ? 'active-variant' : ''}" ${guide.active ? 'open' : ''}>
            <summary>
                <div><span>${guide.active ? '本局生效' : '其他种子'}</span><strong>${escapeHtml(guide.killer_id)} · ${escapeHtml(guide.title)}</strong></div>
                <small>${guide.chain?.length || 0} 段推理链</small>
            </summary>
            <div class="variant-guide-body">
                <div class="deduction-chain">${(guide.chain || []).map((item, index) => renderDeductionStep(item, index, references)).join('')}</div>
                <aside class="deduction-sidebar">
                    <section><h4>必须排除的混淆</h4><ul>${(guide.red_herrings || []).map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul></section>
                    <section class="decisive-conclusion"><h4>理想锁凶结论</h4><p>${escapeHtml(guide.decisive_conclusion)}</p></section>
                    <section><h4>适合主持人推动的事件</h4><div class="evidence-references">${renderEvidenceReferences(guide.recommended_host_cards || [], references)}</div></section>
                </aside>
            </div>
        </details>
    `).join('');
}

function renderDeductionStep(item, index, references) {
    return `<article class="deduction-step">
        <span>${String(index + 1).padStart(2, '0')}</span>
        <div><h5>${escapeHtml(item.step)}</h5><p>${escapeHtml(item.reasoning)}</p><div class="evidence-references">${renderEvidenceReferences(item.requires || [], references)}</div></div>
    </article>`;
}

function renderEvidenceReferences(ids, references) {
    return ids.map(id => {
        const reference = references[id] || {label: id, where: '尚未登记', kind: 'unknown'};
        return `<span class="evidence-ref ref-${escapeHtml(reference.kind)}" title="${escapeHtml(reference.where)}"><strong>${escapeHtml(reference.label)}</strong><small>${escapeHtml(reference.where)}</small></span>`;
    }).join('');
}

function renderFileList(title, items = []) {
    return `<section class="file-block"><h4>${escapeHtml(title)}</h4><ul>${items.length
        ? items.map(item => `<li>${escapeHtml(typeof item === 'string' ? item : item.claim || JSON.stringify(item))}</li>`).join('')
        : '<li>未记录。</li>'}</ul></section>`;
}

function renderPlan(plan) {
    const entries = Object.entries(plan || {});
    if (!entries.length) return '<p>尚未形成明确计划。</p>';
    return `<dl class="plan-ledger">${entries.map(([key, value]) => `
        <dt>${escapeHtml(key)}</dt><dd>${escapeHtml(Array.isArray(value) ? value.join('；') : typeof value === 'object' ? JSON.stringify(value) : value)}</dd>
    `).join('')}</dl>`;
}

function lifeLabel(value) {
    return ({alive: '健康', injured: '受伤', dead: '死亡'})[value] || value;
}

function plannerLabel(value = '') {
    if (value.startsWith('ollama:')) return 'Ollama 本地';
    if (value.startsWith('deepseek:')) return `DeepSeek · ${value.slice('deepseek:'.length)}`;
    if (value.startsWith('project:')) return `项目配置 · ${value.slice('project:'.length)}`;
    return value || '在线模型';
}

function renderCards(cards, emptyEvent = null, activeCardId = null) {
    availableCards = [...cards, ...(emptyEvent ? [emptyEvent] : [])];
    selectedCardId = activeCardId;
    ui.cards.innerHTML = cards.length ? cards.map(card => `
        <button class="event-card" data-card-id="${escapeHtml(card.card_id)}">
            <span class="card-category">${escapeHtml(categoryLabels[card.category] || card.category)}</span>
            <h3>${escapeHtml(card.title)}</h3>
            <p>${escapeHtml(card.description)}</p>
            <p class="impact-preview">${escapeHtml(card.impact_preview)}</p>
        </button>
    `).join('') : `<p class="timeline-meta">${activeCardId ? '本轮事件卡已经确定，可以继续推演。' : '没有更多事件卡。'}</p>`;
    ui.emptyEvent.innerHTML = emptyEvent ? `
        <button class="empty-event-card" data-card-id="${escapeHtml(emptyEvent.card_id)}">
            <strong>${escapeHtml(emptyEvent.title)}</strong> · ${escapeHtml(emptyEvent.description)}
        </button>
    ` : '';

    document.querySelectorAll('#event-cards [data-card-id], #empty-event-option [data-card-id]').forEach(cardElement => {
        cardElement.addEventListener('click', async () => {
            if (!gameId || currentState.phase !== 'intervention') return;
            const cardId = cardElement.dataset.cardId;
            setBusy(true, '正在将事件写入世界……');
            try {
                const data = await api(`/api/interactive/games/${gameId}/event-card`, {
                    method: 'POST',
                    body: JSON.stringify({card_id: cardId}),
                });
                selectedCardId = cardId;
                renderState(data.state);
                const selectedCard = availableCards.find(card => (card.card_id || card.id) === cardId);
                if (selectedCard) showDirectorDispatch('event', selectedCard);
                document.querySelectorAll('#event-cards [data-card-id], #empty-event-option [data-card-id]').forEach(element => {
                    element.disabled = true;
                    element.classList.toggle('selected', element.dataset.cardId === cardId);
                });
                ui.selectedCard.textContent = `已选择：${cardElement.querySelector('h3, strong').textContent}`;
                ui.actionHint.textContent = data.state.player_controlled
                    ? '事件已进入世界，等待角色席提交本轮第一次行动。'
                    : '事件已进入世界，可以开始整轮的三次连续行动。';
            } catch (error) {
                showToast(error.message);
            } finally {
                setBusy(false);
            }
        });
    });
    setBusy(false);
}

function renderIntel(intelOptions, state) {
    if (!ui.intelOptions) return;
    if (state.active_public_intel) {
        ui.intelOptions.innerHTML = '<p class="timeline-meta">本轮公开情报已经广播，下一轮可再次选择。</p>';
        return;
    }
    ui.intelOptions.innerHTML = intelOptions.length ? intelOptions.map(intel => `
        <button class="intel-option" data-intel-id="${escapeHtml(intel.id)}">
            <span>${escapeHtml(intel.source)} · 可信度 ${Math.round(Number(intel.reliability || 0) * 100)}%</span>
            <strong>${escapeHtml(intel.title)}</strong>
            <p>${escapeHtml(intel.claim)}</p>
        </button>
    `).join('') : '<p class="timeline-meta">公开情报池已经用尽。</p>';
    ui.intelOptions.querySelectorAll('[data-intel-id]').forEach(button => {
        button.addEventListener('click', async () => {
            if (!gameId || !['intervention', 'ready'].includes(currentState.phase)) return;
            setBusy(true, '正在向六名角色广播公开情报……');
            try {
                const data = await api(`/api/interactive/games/${gameId}/public-intel`, {
                    method: 'POST',
                    body: JSON.stringify({intel_id: button.dataset.intelId}),
                });
                renderState(data.state);
                renderIntel([], data.state);
                showDirectorDispatch('intel', data.intel);
                showToast('公开情报已传达给六名角色，并写入各自记忆。');
            } catch (error) {
                showToast(error.message);
            } finally {
                setBusy(false);
            }
        });
    });
}

async function loadScenarios() {
    try {
        const data = await api('/api/interactive/scenarios');
        const scenario = data.scenarios[0];
        if (!scenario) throw new Error('没有找到可用情景');
        ui.premise.textContent = scenario.premise;
        ui.create.dataset.scenarioId = scenario.id;
        ui.create.disabled = false;
        const savedGameId = window.localStorage.getItem('interactiveGameId');
        if (savedGameId) {
            try {
                const saved = await api(`/api/interactive/games/${savedGameId}`);
                gameId = savedGameId;
                ui.landing.classList.add('hidden');
                ui.game.classList.remove('hidden');
                renderState(saved.state);
                renderCards(saved.cards, saved.empty_event, saved.state.active_event_card);
                renderIntel(saved.intel || [], saved.state);
                ui.actionHint.textContent = saved.state.phase === 'finished'
                    ? '这局推演已经结束，可以查看终局复盘。'
                    : saved.state.active_event_card
                        ? '已恢复待推进的回合。'
                        : '已恢复游戏，可以继续发布公告并选择事件卡。';
            } catch (restoreError) {
                window.localStorage.removeItem('interactiveGameId');
            }
        }
    } catch (error) {
        ui.premise.textContent = error.message;
    }
}

ui.create.addEventListener('click', async () => {
    setBusy(true, '正在布置停云客栈……');
    try {
        const data = await api('/api/interactive/games', {
            method: 'POST',
            body: JSON.stringify({scenario_id: ui.create.dataset.scenarioId, seed: Date.now() % 100000}),
        });
        gameId = data.state.game_id;
        window.localStorage.setItem('interactiveGameId', gameId);
        ui.landing.classList.add('hidden');
        ui.game.classList.remove('hidden');
        renderState(data.state);
        renderCards(data.cards, data.empty_event);
        renderIntel(data.intel || [], data.state);
        ui.actionHint.textContent = '可以先张贴公告，也可以直接选择第一张事件卡。';
    } catch (error) {
        showToast(error.message);
    } finally {
        setBusy(false);
    }
});

ui.postNotice.addEventListener('click', async () => {
    const content = ui.noticeContent.value.trim();
    if (!content) return showToast('请先填写公告内容。');
    setBusy(true, '正在张贴公告……');
    try {
        await api(`/api/interactive/games/${gameId}/notices`, {
            method: 'POST',
            body: JSON.stringify({content}),
        });
        ui.noticeContent.value = '';
        const data = await api(`/api/interactive/games/${gameId}`);
        renderState(data.state);
        renderIntel(data.intel || [], data.state);
        showToast('主持人公告已张贴到大堂公告栏，并立即同步给全员。');
    } catch (error) {
        showToast(error.message);
    } finally {
        setBusy(false);
    }
});

ui.switchPlanner?.addEventListener('click', async () => {
    if (!gameId) return showToast('请先创建或载入一局游戏。');
    ui.switchPlanner.disabled = true;
    try {
        const data = await api(`/api/interactive/games/${gameId}/planner`, {
            method: 'POST',
            body: JSON.stringify({
                provider: ui.plannerProvider.value,
                model: ui.plannerModel.value.trim(),
            }),
        });
        ui.planner.textContent = `已切换 · ${data.planner_provider}`;
        showToast(`后续行动将使用 ${data.planner_provider}`);
    } catch (error) {
        showToast(error.message);
    } finally {
        ui.switchPlanner.disabled = false;
    }
});

ui.advance.addEventListener('click', async () => {
    setBusy(true, '六名角色正在同时决定本轮行动……');
    try {
        const queued = await api(`/api/interactive/games/${gameId}/rounds/advance`, {method: 'POST', body: '{}'});
        const data = await waitForRoundTask(queued.task_id);
        selectedCardId = null;
        renderState(data.state);
        renderCards(data.cards, data.empty_event);
        renderIntel(data.intel || [], data.state);
        if (data.state.phase !== 'finished') ui.actionHint.textContent = '查看本轮结果，然后为下一轮发布公告并选择事件。';
    } catch (error) {
        showToast(error.message);
    } finally {
        setBusy(false);
    }
});

ui.viewRecap?.addEventListener('click', async () => {
    setBusy(true, '正在整理结构化复盘……');
    try {
        const data = await api(`/api/interactive/games/${gameId}/recap`);
        renderRecap(data.recap, data.story_outline);
        ui.recapPanel.classList.remove('hidden');
        ui.recapPanel.scrollIntoView({behavior: 'smooth', block: 'start'});
    } catch (error) {
        showToast(error.message);
    } finally {
        setBusy(false);
    }
});

ui.exportTimeline?.addEventListener('click', () => {
    if (!gameId) return;
    const link = document.createElement('a');
    link.href = `/api/interactive/games/${encodeURIComponent(gameId)}/timeline.txt`;
    link.download = `${gameId}-action-timeline.txt`;
    document.body.appendChild(link);
    link.click();
    link.remove();
});

ui.closeRecap?.addEventListener('click', () => {
    ui.recapPanel.classList.add('hidden');
    ui.game.scrollIntoView({behavior: 'smooth', block: 'start'});
});

function renderRecap(recap, storyOutline) {
    const timeline = Object.entries(recap.timeline).map(([round, events]) => {
        const selected = events.filter(event => [
      'poison_effect', 'discovery', 'object_transfer', 'treatment',
      'move', 'conversation', 'vote_cast', 'killer_revealed',
            'public_fact', 'public_intel', 'event_card_selected', 'notice_posted'
        ].includes(event.event_type));
        const visible = selected.length ? selected : events;
        return `<li><strong>第 ${escapeHtml(round)} 轮：</strong>${visible.map(event => escapeHtml(event.summary)).join('；')}</li>`;
    }).join('');
    const voting = recap.voting_result || {};
    ui.recapContent.innerHTML = `
        <section class="recap-section">
            <h3>客观真相</h3>
            <ul>${recap.objective_truths.map(truth => `<li>${escapeHtml(truth.claim)}</li>`).join('')}</ul>
        </section>
        <section class="recap-section">
            <h3>玩家公告</h3>
            <ul>${recap.player_notices.length ? recap.player_notices.map(notice => `<li>“${escapeHtml(notice.content)}”触达 ${notice.reach}/${notice.participant_count} 人</li>`).join('') : '<li>本局没有发布公告。</li>'}</ul>
        </section>
        <section class="recap-section full">
            <h3>人物结局</h3>
            <div class="recap-character-grid">${recap.characters.map(character => `
                <article class="recap-character">
                    <strong>${escapeHtml(character.display_name)}</strong>
                    <span>${escapeHtml(lifeLabel(character.life_state))} · ${character.score || 0} 分<br>${escapeHtml(character.final_location)}<br>模型：${escapeHtml((character.models || []).join('、') || '未记录')}<br>客观题：${(character.answer_results || []).filter(item => item.is_correct).length}/${(character.answer_results || []).length}</span>
                </article>
            `).join('')}</div>
        </section>
        <section class="recap-section full">
            <h3>终局投票</h3>
            <p>${escapeHtml(voting.outcome || '本局没有形成投票结果。')}</p>
            <ul>${(voting.votes || []).map(vote => `<li>${escapeHtml(vote.voter_name)} → ${escapeHtml(vote.suspect_name)}：${escapeHtml(vote.reason)}</li>`).join('')}</ul>
            ${voting.killer_name ? `<p><strong>真实凶手：${escapeHtml(voting.killer_name)}</strong></p>` : ''}
        </section>
        <section class="recap-section full">
            <h3>六轮十八次行动事件线</h3>
            <ul>${timeline}</ul>
        </section>
        <section class="recap-section full">
            <h3>三幕故事编排</h3>
            ${storyOutline.acts.map(act => `
                <h4>${escapeHtml(act.title)} <span class="timeline-meta">第 ${act.start_round}—${act.end_round} 轮</span></h4>
                <ul>${act.events.length ? act.events.map(event => `<li>${escapeHtml(event.summary)} <code>${escapeHtml(event.event_id)}</code></li>`).join('') : '<li>本幕没有形成关键事件，需要调整节奏。</li>'}</ul>
            `).join('')}
        </section>
        <section class="recap-section full">
            <h3>尚待回答</h3>
            <ul>${recap.ending_questions.map(question => `<li>${escapeHtml(question)}</li>`).join('')}</ul>
        </section>
    `;
}

loadScenarios();
window.setInterval(pollDirectorState, 1000);
pollHostNotifications();
window.setInterval(pollHostNotifications, 1000);
