const liveUi = {
    landing: document.getElementById('live-landing'),
    app: document.getElementById('live-app'),
    premise: document.getElementById('live-premise'),
    create: document.getElementById('live-create'),
    roleOptions: document.getElementById('role-options'),
    title: document.getElementById('live-title'),
    status: document.getElementById('live-status'),
    round: document.getElementById('live-round'),
    maxRounds: document.getElementById('live-max-rounds'),
    actionStep: document.getElementById('live-action-step'),
    viewMode: document.getElementById('live-view-mode'),
    gameId: document.getElementById('live-game-id'),
    planner: document.getElementById('live-planner'),
    map: document.getElementById('live-map'),
    bulletinBoard: document.getElementById('bulletin-board'),
    bulletinPosts: document.getElementById('bulletin-posts'),
    bulletinLocationHint: document.getElementById('bulletin-location-hint'),
    playerBulletinComposer: document.getElementById('player-bulletin-composer'),
    playerBulletinContent: document.getElementById('player-bulletin-content'),
    postPlayerBulletin: document.getElementById('post-player-bulletin'),
    feed: document.getElementById('live-feed'),
    focus: document.getElementById('event-focus'),
    focusType: document.getElementById('focus-type'),
    focusTitle: document.getElementById('focus-title'),
    focusLocation: document.getElementById('focus-location'),
    tracks: document.getElementById('agent-tracks'),
    tracksPanel: document.getElementById('tracks-panel'),
    playerActionColumn: document.getElementById('player-action-column'),
    observerEventPanel: document.getElementById('observer-event-panel'),
    playerName: document.getElementById('player-name'),
    storyPlayerName: document.getElementById('story-player-name'),
    playerRole: document.getElementById('player-role'),
    playerGoals: document.getElementById('player-goals'),
    playerScore: document.getElementById('player-score'),
    playerSecrets: document.getElementById('player-secrets'),
    playerInventory: document.getElementById('player-inventory'),
    playerMemories: document.getElementById('player-memories'),
    playerAbilities: document.getElementById('player-abilities'),
    privateMemoryCount: document.getElementById('private-memory-count'),
    storyGuideTitle: document.getElementById('story-guide-title'),
    storyGuideLocation: document.getElementById('story-guide-location'),
    storyGuideSituation: document.getElementById('story-guide-situation'),
    storyGuideRecent: document.getElementById('story-guide-recent'),
    storyGuideObjective: document.getElementById('story-guide-objective'),
    storyGuideSuggestions: document.getElementById('story-guide-suggestions'),
    openingOverlay: document.getElementById('opening-overlay'),
    openingDispatch: document.getElementById('opening-dispatch'),
    openingClassification: document.getElementById('opening-classification'),
    openingTitle: document.getElementById('opening-title'),
    openingBody: document.getElementById('opening-body'),
    openingSignature: document.getElementById('opening-signature'),
    openingNote: document.getElementById('opening-note'),
    enterFromDispatch: document.getElementById('enter-from-dispatch'),
    storyOverlay: document.getElementById('story-overlay'),
    storyScroll: document.getElementById('story-scroll'),
    storyHook: document.getElementById('story-hook'),
    storyBody: document.getElementById('story-body'),
    storyMemorySection: document.getElementById('story-memory-section'),
    dossierEdgeTabs: document.getElementById('dossier-edge-tabs'),
    openCharacterScroll: document.getElementById('open-character-scroll'),
    openMemoryScroll: document.getElementById('open-memory-scroll'),
    detailOverlay: document.getElementById('detail-overlay'),
    detailKicker: document.getElementById('detail-kicker'),
    detailTitle: document.getElementById('detail-title'),
    detailBody: document.getElementById('detail-body'),
    detailClose: document.getElementById('detail-close'),
    playerEventFeedback: document.getElementById('player-event-feedback'),
    playerEventKicker: document.getElementById('player-event-kicker'),
    playerEventTitle: document.getElementById('player-event-title'),
    playerEventSummary: document.getElementById('player-event-summary'),
    playerEventDetail: document.getElementById('player-event-detail'),
    playerEventReply: document.getElementById('player-event-reply'),
    playerEventClose: document.getElementById('player-event-close'),
    decisionTitle: document.getElementById('decision-title'),
    decisionLocation: document.getElementById('decision-location'),
    actionTypeGrid: document.getElementById('action-type-grid'),
    actionFields: document.getElementById('action-fields'),
    destinationField: document.getElementById('destination-field'),
    targetField: document.getElementById('target-field'),
    objectField: document.getElementById('object-field'),
    memoryField: document.getElementById('memory-field'),
    contentField: document.getElementById('content-field'),
    destination: document.getElementById('action-destination'),
    target: document.getElementById('action-target'),
    object: document.getElementById('action-object'),
    memory: document.getElementById('action-memory'),
    content: document.getElementById('action-content'),
    submitAction: document.getElementById('submit-action'),
    actionProgress: document.getElementById('action-progress'),
    actionProgressLabel: document.getElementById('action-progress-label'),
    actionProgressCount: document.getElementById('action-progress-count'),
    actionProgressBar: document.getElementById('action-progress-bar'),
    actionProgressAgents: document.getElementById('action-progress-agents'),
    endPlayerRound: document.getElementById('end-player-round'),
    autoHostNextRound: document.getElementById('auto-host-next-round'),
    decisionHint: document.getElementById('decision-hint'),
    playerVotePanel: document.getElementById('player-vote-panel'),
    playerVoteTarget: document.getElementById('player-vote-target'),
    playerVoteReason: document.getElementById('player-vote-reason'),
    submitPlayerVote: document.getElementById('submit-player-vote'),
    finalDiscussionPanel: document.getElementById('final-discussion-panel'),
    openFinalVoting: document.getElementById('open-final-voting'),
    conversationArchive: document.getElementById('conversation-archive'),
    conversationTabs: document.getElementById('conversation-tabs'),
    conversationThread: document.getElementById('conversation-thread'),
    votePanel: document.getElementById('vote-panel'),
    voteResult: document.getElementById('vote-result'),
    dispatchLayer: document.getElementById('live-dispatch-layer'),
    toast: document.getElementById('live-toast'),
};

const agentColors = ['#d7a95f', '#81a18e', '#c27868', '#8d9fc7', '#b994c1', '#d09262', '#7fa8aa', '#c2b56d'];
const playbackScale = new URLSearchParams(window.location.search).get('speed') === 'fast' ? 0.06 : 1;
const actionLabels = {
    move: '移动', discovery: '发现', investigation_empty: '搜查', conversation: '对话',
    object_transfer: '交付', object_hidden: '藏匿', attack: '冲突', attack_failed: '冲突未遂',
    treatment: '治疗', wait: '观察', action_failed: '行动失败', escape: '逃脱',
    final_discussion: '终局公议',
    escape_failed: '逃脱未遂', public_fact: '局势', public_intel: '公开情报',
    event_card_selected: '事件卡', notice_posted: '公告', vote_cast: '投票', killer_revealed: '揭晓',
};
const intentLabels = {
    move: '移动', investigate: '搜查', talk: '交谈', transfer: '交付', hide: '藏匿',
    attack: '冲突', treat: '治疗', escape: '尝试离开', wait: '留在原地',
};

let gameId = null;
let liveState = null;
let visualLocations = {};
let eventQueue = [];
let queuedIds = new Set();
let playing = false;
let pollTimer = null;
let historyCursor = 0;
let playerToken = null;
let viewMode = 'observer';
let selectedActionType = null;
let selectedAbilityId = null;
let lastPlayerRenderKey = '';
let pendingPlayerEntry = null;
let feedbackDismiss = null;
let pendingReplyEvent = null;
let selectedConversationKey = null;

function escapeHtml(value) {
    return String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#039;');
}

async function liveApi(path, options = {}) {
    const response = await fetch(path, {headers: {'Content-Type': 'application/json'}, ...options});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `请求失败（${response.status}）`);
    return data;
}

async function playerApi(path, options = {}) {
    return liveApi(path, {
        ...options,
        headers: {
            'Content-Type': 'application/json',
            'X-Player-Token': playerToken || '',
            ...(options.headers || {}),
        },
    });
}

async function waitForPlayerTask(taskId) {
    liveUi.actionProgress?.classList.remove('hidden');
    for (let attempt = 0; attempt < 300; attempt += 1) {
        const task = await liveApi(`/api/interactive/tasks/${taskId}`);
        const progress = task.progress || {};
        const completed = Number(progress.completed || 0);
        const total = Number(progress.total || 0);
        const percentage = total > 0 ? Math.min(100, Math.round(completed / total * 100)) : 12;
        liveUi.actionProgressLabel.textContent = task.message || '其他密探正在决定行动';
        liveUi.actionProgressCount.textContent = total > 0 ? `${completed}/${total}` : '处理中';
        liveUi.actionProgressBar.style.width = `${percentage}%`;
        liveUi.actionProgressAgents.innerHTML = Object.values(progress.agents || {}).map(agent =>
            `<span class="${agent.status === 'completed' ? 'done' : ''}">${escapeHtml(agent.display_name)}</span>`
        ).join('');
        if (task.status === 'succeeded') {
            liveUi.actionProgressBar.style.width = '100%';
            window.setTimeout(() => liveUi.actionProgress.classList.add('hidden'), 450);
            return task.result;
        }
        if (task.status === 'failed') throw new Error(task.error || '行动结算失败');
        await new Promise(resolve => window.setTimeout(resolve, 700));
    }
    throw new Error('行动结算等待超时，请刷新页面恢复本局。');
}

function showLiveToast(message) {
    liveUi.toast.textContent = message;
    liveUi.toast.classList.remove('hidden');
    window.clearTimeout(showLiveToast.timer);
    showLiveToast.timer = window.setTimeout(() => liveUi.toast.classList.add('hidden'), 3200);
}

function inspectableTag(title, body, kicker = '卷宗细目') {
    return `<button type="button" class="inspectable-tag"
        data-detail-title="${escapeHtml(title)}"
        data-detail-body="${escapeHtml(body)}"
        data-detail-kicker="${escapeHtml(kicker)}">${escapeHtml(title)}</button>`;
}

function showDetail(title, body, kicker = '卷宗细目') {
    liveUi.detailKicker.textContent = kicker;
    liveUi.detailTitle.textContent = title;
    liveUi.detailBody.textContent = body;
    liveUi.detailOverlay.classList.remove('hidden');
    liveUi.detailOverlay.setAttribute('aria-hidden', 'false');
    requestAnimationFrame(() => liveUi.detailOverlay.classList.add('shown'));
}

function hideDetail() {
    liveUi.detailOverlay.classList.remove('shown');
    window.setTimeout(() => {
        liveUi.detailOverlay.classList.add('hidden');
        liveUi.detailOverlay.setAttribute('aria-hidden', 'true');
    }, 220);
}

function bindInspectableTags(container) {
    container?.querySelectorAll('.inspectable-tag').forEach(button => {
        button.addEventListener('click', () => showDetail(
            button.dataset.detailTitle,
            button.dataset.detailBody,
            button.dataset.detailKicker,
        ));
    });
}

function renderStoryGuide(state) {
    const guide = state.story_guide || {};
    liveUi.storyGuideTitle.textContent = guide.title || '风雨中的停云客栈';
    liveUi.storyGuideLocation.textContent = guide.location_name || '停云客栈';
    liveUi.storyGuideSituation.textContent = guide.situation || '观察当前局势，决定你的下一步。';
    liveUi.storyGuideObjective.textContent = guide.objective || '根据自己的记忆作出选择。';
    liveUi.storyGuideRecent.textContent = guide.recent_event ? `刚刚发生：${guide.recent_event}` : '';
    liveUi.storyGuideRecent.classList.toggle('hidden', !guide.recent_event);
    liveUi.storyGuideSuggestions.innerHTML = (guide.suggestions || [])
        .map(item => inspectableTag(item, `${item}。这是一条剧情方向提示，不会替你自动作出决定。`, '行动提示'))
        .join('');
    bindInspectableTags(liveUi.storyGuideSuggestions);
}

function showStoryScroll(section = 'story') {
    if (viewMode !== 'player') return;
    liveUi.dossierEdgeTabs.classList.add('hidden');
    liveUi.storyOverlay.classList.remove('hidden');
    liveUi.storyOverlay.setAttribute('aria-hidden', 'false');
    liveUi.storyScroll.classList.remove('rolling');
    requestAnimationFrame(() => liveUi.storyScroll.classList.add('unfurled'));
    if (section === 'memory') {
        window.setTimeout(() => liveUi.storyMemorySection.scrollIntoView({behavior: 'smooth', block: 'center'}), 360);
    } else {
        liveUi.storyOverlay.scrollTop = 0;
    }
}

function hideStoryScroll() {
    if (liveUi.storyOverlay.classList.contains('hidden')) return;
    liveUi.storyScroll.classList.remove('unfurled');
    liveUi.storyScroll.classList.add('rolling');
    window.setTimeout(() => {
        liveUi.storyOverlay.classList.add('hidden');
        liveUi.storyOverlay.setAttribute('aria-hidden', 'true');
        liveUi.storyScroll.classList.remove('rolling');
        if (viewMode === 'player') liveUi.dossierEdgeTabs.classList.remove('hidden');
    }, 520);
}

function prepareOpeningDispatch(state) {
    const dispatch = state.opening_dispatch || {};
    liveUi.openingClassification.textContent = dispatch.classification || '绣衣楼绝密 · 阅后即焚';
    liveUi.openingTitle.textContent = dispatch.title || '西驿急递';
    liveUi.openingBody.innerHTML = (dispatch.body || []).map(line => `<p>${escapeHtml(line)}</p>`).join('');
    liveUi.openingSignature.textContent = dispatch.signature || '';
    liveUi.openingNote.textContent = dispatch.dead_note || '陆成临终：鸢报有假。';
    liveUi.openingOverlay.classList.remove('hidden');
    liveUi.openingOverlay.setAttribute('aria-hidden', 'false');
    requestAnimationFrame(() => liveUi.openingDispatch.classList.add('unfurled'));
}

function completeOpening() {
    if (!pendingPlayerEntry) return;
    const entry = pendingPlayerEntry;
    pendingPlayerEntry = null;
    liveUi.enterFromDispatch.disabled = true;
    liveUi.openingDispatch.classList.remove('unfurled');
    liveUi.openingDispatch.classList.add('rolling');
    window.setTimeout(() => {
        liveUi.openingOverlay.classList.add('hidden');
        liveUi.openingOverlay.setAttribute('aria-hidden', 'true');
        liveUi.openingDispatch.classList.remove('rolling');
        liveUi.enterFromDispatch.disabled = false;
        liveUi.app.classList.remove('hidden');
        receivePlayerState(entry.player, {initial: true});
        window.clearTimeout(pollTimer);
        pollGame();
        window.setTimeout(() => showStoryScroll('story'), 480);
        showLiveToast('你已入席。读完角色卷宗后，等待主持人选择第一轮事件。');
    }, 620);
}

function showLiveDispatch(event) {
    if (!liveUi.dispatchLayer) return;
    liveUi.dispatchLayer.replaceChildren();
    const isIntel = event.event_type === 'public_intel';
    const payload = event.payload || {};
    const card = document.createElement('article');
    card.className = `dispatch-card ${isIntel ? 'yuan-report' : 'world-card'}`;
    const reliability = isIntel && payload.reliability != null
        ? ` · 可信度 ${Math.round(Number(payload.reliability) * 100)}%`
        : '';
    card.innerHTML = `
        <button class="dispatch-close" type="button" aria-label="收起">×</button>
        <span class="dispatch-kicker">${isIntel ? '鸢报送达' : '局势事件展开'}</span>
        <h2>${escapeHtml(payload.title || (isIntel ? '公开情报' : '新的变局'))}</h2>
        <p>${escapeHtml(payload.claim || payload.description || event.summary)}</p>
        <footer>${escapeHtml(isIntel ? `${payload.source || '来源不明'}${reliability}` : payload.impact_preview || '客栈中的每个人都将面对这一变化')}</footer>`;
    liveUi.dispatchLayer.appendChild(card);
    requestAnimationFrame(() => card.classList.add('shown'));
    const dismiss = () => {
        card.classList.remove('shown');
        window.setTimeout(() => card.remove(), 360);
    };
    card.querySelector('.dispatch-close').addEventListener('click', dismiss);
    window.setTimeout(dismiss, 6800);
}

function hidePlayerEventFeedback() {
    if (!liveUi.playerEventFeedback || liveUi.playerEventFeedback.classList.contains('hidden')) return;
    window.clearTimeout(showPlayerEventFeedback.timer);
    liveUi.playerEventFeedback.classList.remove('shown');
    window.setTimeout(() => {
        liveUi.playerEventFeedback.classList.add('hidden');
        liveUi.playerEventFeedback.setAttribute('aria-hidden', 'true');
        const resolve = feedbackDismiss;
        feedbackDismiss = null;
        if (resolve) resolve();
    }, 220);
}

function showPlayerEventFeedback(event) {
    if (!liveUi.playerEventFeedback) return Promise.resolve();
    const ownAction = event.actors?.[0] === liveState?.self?.agent_id;
    const freeAction = Boolean(event.payload?.free_action);
    const isReply = Boolean(event.payload?.is_reply);
    const invitesReply = Boolean(event.payload?.player_reply_invited);
    const speakerId = event.payload?.speaker_id || event.actors?.[0];
    const speakerName = liveState?.agents?.[speakerId]?.display_name || speakerId || '对方';
    liveUi.playerEventKicker.textContent = isReply
        ? `${speakerName}回应了你`
        : invitesReply
            ? `${speakerName}正在与你交谈`
            : freeAction
        ? '自由探索 · 不消耗主要行动'
        : ownAction ? '你的行动产生了新结果' : '你在现场目睹了新的行动';
    liveUi.playerEventTitle.textContent = isReply
        ? `${speakerName}的回应`
        : `${actionLabels[event.event_type] || '新情况'} · ${eventLocationName(event)}`;
    liveUi.playerEventSummary.textContent = (isReply || invitesReply)
        ? (event.payload?.content || event.summary)
        : event.summary;
    const detail = ownAction && event.event_type === 'discovery'
        ? String(event.payload?.clue_claim || '')
        : '';
    liveUi.playerEventDetail.textContent = detail;
    liveUi.playerEventDetail.classList.toggle('hidden', !detail || detail === event.summary);
    liveUi.playerEventReply?.classList.toggle('hidden', !invitesReply);
    pendingReplyEvent = invitesReply ? event : null;
    liveUi.playerEventFeedback.classList.remove('hidden');
    liveUi.playerEventFeedback.setAttribute('aria-hidden', 'false');
    requestAnimationFrame(() => liveUi.playerEventFeedback.classList.add('shown'));
    window.clearTimeout(showPlayerEventFeedback.timer);
    return new Promise(resolve => {
        feedbackDismiss = resolve;
    });
}

function delay(milliseconds) { return new Promise(resolve => window.setTimeout(resolve, milliseconds * playbackScale)); }

function eventLocationName(event) {
    return liveState?.locations?.[event.location_id]?.name || '全局事件';
}

function buildMap(state) {
    const byFloor = Object.values(state.locations).reduce((result, location) => {
        const floor = Number(location.layout?.floor || 1);
        (result[floor] ||= []).push(location);
        return result;
    }, {});
    const floorSections = Object.entries(byFloor)
        .sort(([a], [b]) => Number(a) - Number(b))
        .map(([floor, locations]) => {
            const roomHtml = locations.map(location => {
                const layout = location.layout || {x: 1, y: 1, w: 1, h: 1};
                return `<article class="live-room" data-location-id="${escapeHtml(location.id)}" style="grid-column:${layout.x} / span ${layout.w};grid-row:${layout.y} / span ${layout.h}">
                    <div class="room-name"><span>${escapeHtml(location.name)}</span><small>${location.public ? '公开' : '隐蔽'}</small></div>
                    <div class="room-description">${escapeHtml(location.description)}</div>
                    <div class="token-layer"></div>
                </article>`;
            }).join('');
            const label = Number(floor) === 1 ? '一层 · 大堂、后院与出口' : '二层 · 客房与回廊';
            return `<section class="floor-stage">
                <div class="floor-label">${label}</div>
                <div class="floor-grid">${roomHtml}</div>
            </section>`;
        });
    liveUi.map.innerHTML = floorSections.join('');
    renderTokens(state);
}

function renderTokens(state) {
    liveUi.map.querySelectorAll('.token-layer').forEach(layer => { layer.innerHTML = ''; });
    Object.values(state.agents).forEach((agent, index) => {
        const locationId = visualLocations[agent.agent_id] || agent.location_id;
        const layer = liveUi.map.querySelector(`[data-location-id="${CSS.escape(locationId)}"] .token-layer`);
        if (!layer) return;
        const token = document.createElement('div');
        token.className = `agent-token ${agent.conditions?.includes('escaped') ? 'escaped' : ''}`;
        token.dataset.agentId = agent.agent_id;
        token.style.setProperty('--agent-color', agentColors[index % agentColors.length]);
        token.innerHTML = `<span class="portrait">${escapeHtml(agent.display_name.slice(0, 1))}</span><span>${escapeHtml(agent.display_name)}</span>`;
        layer.appendChild(token);
    });
}

async function animateMove(event) {
    const actorId = event.actors?.[0];
    const destination = event.payload?.destination_id || event.state_changes?.find(change => change.agent_id === actorId)?.location_id;
    const token = liveUi.map.querySelector(`[data-agent-id="${CSS.escape(actorId || '')}"]`);
    const destinationLayer = liveUi.map.querySelector(`[data-location-id="${CSS.escape(destination || '')}"] .token-layer`);
    if (!token || !destinationLayer) return;
    const before = token.getBoundingClientRect();
    destinationLayer.appendChild(token);
    const after = token.getBoundingClientRect();
    visualLocations[actorId] = destination;
    await token.animate([
        {transform: `translate(${before.left - after.left}px, ${before.top - after.top}px)`, zIndex: 30},
        {transform: 'translate(0, 0)', zIndex: 30},
    ], {duration: 780 * playbackScale, easing: 'cubic-bezier(.2,.78,.25,1)'}).finished.catch(() => {});
}

async function showConversation(event) {
    const speakerId = event.payload?.speaker_id || event.actors?.[0];
    const token = liveUi.map.querySelector(`[data-agent-id="${CSS.escape(speakerId || '')}"]`);
    if (!token) return;
    token.classList.add('speaking');
    const bubble = document.createElement('div');
    bubble.className = 'speech-bubble';
    bubble.textContent = event.payload?.content || event.summary;
    token.appendChild(bubble);
    await delay(1800);
    bubble.remove();
    token.classList.remove('speaking');
}

function highlightLocation(locationId) {
    liveUi.map.querySelectorAll('.live-room.active').forEach(room => room.classList.remove('active'));
    if (!locationId) return;
    liveUi.map.querySelector(`[data-location-id="${CSS.escape(locationId)}"]`)?.classList.add('active');
}

function addFeedEvent(event) {
    if (liveUi.feed.querySelector(`[data-event-id="${CSS.escape(event.event_id)}"]`)) return;
    const item = document.createElement('article');
    item.className = 'feed-item';
    item.dataset.eventId = event.event_id;
    item.style.setProperty('--event-color', event.event_type === 'conversation' ? '#81a18e' : event.event_type.includes('escape') ? '#c27868' : '#d7a95f');
    item.innerHTML = `<strong>${escapeHtml(event.summary)}</strong><span>第 ${event.round_number} 轮 · ${escapeHtml(actionLabels[event.event_type] || event.event_type)} · ${escapeHtml(eventLocationName(event))}</span>`;
    liveUi.feed.prepend(item);
}

function focusEvent(event) {
    liveUi.focus.classList.remove('idle');
    liveUi.focus.classList.add('playing');
    liveUi.focusType.textContent = actionLabels[event.event_type] || event.event_type;
    liveUi.focusTitle.textContent = event.summary;
    liveUi.focusLocation.textContent = `第 ${event.round_number} 轮 · ${eventLocationName(event)}`;
    highlightLocation(event.location_id);
}

async function playEvent(event) {
    if (['event_card_selected', 'public_intel'].includes(event.event_type)) {
        showLiveDispatch(event);
        await delay(700);
    }
    focusEvent(event);
    addFeedEvent(event);
    if (event.event_type === 'move') await animateMove(event);
    if (event.event_type === 'conversation') await showConversation(event);
    if (!['move', 'conversation'].includes(event.event_type)) await delay(event.actors?.length ? 850 : 540);
    if (
        viewMode === 'player'
        && !['event_card_selected', 'public_intel', 'public_fact', 'object_hint', 'notice_posted', 'vote_cast', 'killer_revealed'].includes(event.event_type)
        && !event.payload?.awaiting_reply
        && !event.payload?.suppress_player_feedback
    ) {
        await showPlayerEventFeedback(event);
    }
    liveUi.focus.classList.remove('playing');
}

async function drainQueue() {
    if (playing) return;
    playing = true;
    liveUi.status.classList.add('resolving');
    while (eventQueue.length) {
        const event = eventQueue.shift();
        await playEvent(event);
        historyCursor += 1;
        window.localStorage.setItem(`interactiveLiveCursor:${gameId}`, String(historyCursor));
    }
    playing = false;
    liveUi.status.classList.remove('resolving');
    if (viewMode !== 'player') renderTracks(liveState);
    if (liveState) renderVoting(liveState);
    if (liveUi.openFinalVoting && liveState?.phase === 'discussion') {
        liveUi.openFinalVoting.disabled = false;
        liveUi.openFinalVoting.textContent = '结束讨论 · 进入最终投票';
    }
}

function renderTracks(state) {
    const actionTypes = new Set(['move', 'discovery', 'investigation_empty', 'conversation', 'object_transfer', 'object_hidden', 'attack', 'attack_failed', 'treatment', 'wait', 'action_failed', 'escape', 'escape_failed', 'vote_cast']);
    liveUi.tracks.innerHTML = Object.values(state.agents).map((agent, index) => {
        const events = state.events.filter(event => actionTypes.has(event.event_type) && event.actors?.includes(agent.agent_id)).slice(-6).reverse();
        const location = state.locations[agent.location_id]?.name || agent.location_id;
        const condition = agent.conditions?.includes('escaped') ? ' · 已离开客栈' : '';
        return `<article class="track-card" style="--agent-color:${agentColors[index % agentColors.length]}">
            <div class="track-head"><strong>${escapeHtml(agent.display_name)}</strong><span>${escapeHtml(location)}${condition}</span></div>
            <div class="track-role">${escapeHtml(agent.public_role)}</div>
            <ul class="track-events">${events.length ? events.map(event => `<li><em>第 ${event.round_number} 轮 · ${escapeHtml(actionLabels[event.event_type] || event.event_type)}</em><br>${escapeHtml(event.summary)}</li>`).join('') : '<li>尚未采取公开行动。</li>'}</ul>
        </article>`;
    }).join('');
}

function renderVoting(state) {
    const result = state.voting_result;
    if (!result?.killer_name) return liveUi.votePanel.classList.add('hidden');
    liveUi.votePanel.classList.remove('hidden');
    liveUi.voteResult.innerHTML = `<div class="vote-summary">
        <h3>真实凶手：${escapeHtml(result.killer_name)}</h3>
        <p>${escapeHtml(result.outcome)}</p>
        <div class="vote-grid">${(result.votes || []).map(vote => `<article class="vote-card"><strong>${escapeHtml(vote.voter_name)} → ${escapeHtml(vote.suspect_name)}</strong><br>${escapeHtml(vote.reason)}</article>`).join('')}</div>
    </div>`;
}

function renderPlayerPrivateState(state) {
    const actor = state.self;
    const available = state.available_actions || {};
    const background = state.background || {};
    liveUi.playerActionColumn.classList.remove('hidden');
    liveUi.observerEventPanel.classList.add('hidden');
    liveUi.tracksPanel.classList.add('hidden');
    liveUi.playerName.textContent = actor.display_name;
    liveUi.storyPlayerName.textContent = actor.display_name;
    liveUi.playerRole.textContent = background.public_role;
    liveUi.storyHook.textContent = background.opening_hook || '暴雨封住了客栈，也封住了所有人的退路。';
    liveUi.storyBody.innerHTML = (background.story || [])
        .map(paragraph => `<p>${escapeHtml(paragraph)}</p>`).join('');
    liveUi.playerGoals.innerHTML = (background.goals || [])
        .map((goal, index) => inspectableTag(
            `任务 ${index + 1} · ${goal}`,
            `这是你在本局中的个人目标：${goal}。它可能与找出凶手一致，也可能迫使你保留某些信息。`,
            '个人任务',
        )).join('');
    liveUi.playerAbilities.innerHTML = (background.abilities || []).map(ability => inspectableTag(
        `${ability.label} · ${intentLabels[ability.action_type] || ability.action_type}`,
        `${ability.description}\n\n使用方式：在行动区点击带“专属”标记的“${ability.label}”。基础行动仍会单独保留。`,
        ability.hidden ? '只有你知道的能力' : '人物专属能力',
    )).join('') || '<p class="hint">这个角色没有需要主动触发的专属能力。</p>';
    liveUi.playerScore.textContent = String(actor.score || 0);
    liveUi.playerSecrets.innerHTML = (state.known_secrets || []).map(secret => inspectableTag(
        `${secret.owner_id === actor.agent_id ? '我的秘密' : `发现了${secret.owner_id}的秘密`} · ${secret.title}`,
        secret.claim,
        secret.owner_id === actor.agent_id ? '必须谨慎保守' : '你已经识破',
    )).join('') || '<p class="hint">你还没有识破别人隐藏的秘密。</p>';
    const inventory = Object.values(state.visible_objects || {}).filter(item => item.holder_id === actor.agent_id);
    liveUi.playerInventory.innerHTML = inventory.length
        ? inventory.map(item => inspectableTag(
            item.name,
            item.metadata?.description || `这是你当前随身携带的物品：${item.name}。你可以在适当的行动中交付或藏匿它。`,
            '随身物品',
        )).join('')
        : '<p class="hint">你没有随身物品。</p>';
    const conversationSources = new Set((state.conversations || []).map(item => item.event_id));
    const memories = [...(actor.beliefs || [])]
        .filter(memory => !conversationSources.has(memory.source))
        .reverse();
    liveUi.playerMemories.innerHTML = memories.map((memory, index) => inspectableTag(
        `记忆 ${memories.length - index} · ${memory.claim.slice(0, 28)}${memory.claim.length > 28 ? '…' : ''}`,
        `${memory.claim}\n\n来源：${memory.source}；可信度 ${Math.round(Number(memory.confidence || 0) * 100)}%；第 ${memory.learned_round} 轮获得。`,
        memory.learned_round === 0 ? '入局前的记忆' : `第 ${memory.learned_round} 轮的新记忆`,
    )).join('');
    liveUi.privateMemoryCount.textContent = `${memories.length} 条记忆`;
    [liveUi.playerGoals, liveUi.playerSecrets, liveUi.playerInventory, liveUi.playerMemories, liveUi.playerAbilities]
        .forEach(bindInspectableTags);
    renderConversationArchive(state);
    renderBulletin(state);
    renderStoryGuide(state);

    const location = state.locations[actor.location_id];
    liveUi.decisionLocation.textContent = location?.name || actor.location_id;
    const nextRound = Math.min(state.round_number + 1, state.max_rounds);
    const nextStep = Math.min((state.action_step || 0) + 1, state.actions_per_round);
    liveUi.decisionTitle.textContent = state.phase === 'discussion'
        ? '终局公议正在大堂进行'
        : state.phase === 'voting'
        ? '六轮已经结束，请完成最终指认'
        : available.can_submit
            ? `第 ${nextRound} 轮 · 主要行动 ${state.action_step || 0}/${state.actions_per_round}`
            : available.can_auto_host
                ? '由你决定何时展开下一轮'
            : state.active_event_card
                ? '其他角色正在行动'
                : '等待主持人选择本轮事件卡';
    liveUi.endPlayerRound.classList.toggle('hidden', !available.can_end_round);
    liveUi.endPlayerRound.disabled = !available.can_end_round;
    liveUi.autoHostNextRound.classList.toggle('hidden', !available.can_auto_host);
    liveUi.autoHostNextRound.disabled = !available.can_auto_host;
    renderActionComposer(state);
    renderPlayerVoting(state);
    liveUi.finalDiscussionPanel.classList.toggle('hidden', !state.can_open_voting);
    if (state.can_open_voting) {
        const pendingStatements = eventQueue.some(event => event.event_type === 'final_discussion');
        liveUi.openFinalVoting.disabled = pendingStatements || playing;
        liveUi.openFinalVoting.textContent = pendingStatements || playing
            ? '请先读完所有人的终局陈述'
            : '结束讨论 · 进入最终投票';
    }
}

function portraitUrl(name) {
    return `/static/assets/village/agents/${encodeURIComponent(name)}/portrait.png`;
}

function renderConversationArchive(state) {
    const conversations = state.conversations || [];
    liveUi.conversationArchive.classList.toggle('hidden', viewMode !== 'player');
    if (!conversations.length) {
        liveUi.conversationTabs.innerHTML = '<span class="hint">还没有可归档的对话</span>';
        liveUi.conversationThread.innerHTML = '<p class="hint">与同室密探交谈，或在现场听见谈话后，这里会按人物整理。</p>';
        return;
    }
    const selfId = state.self.agent_id;
    const groups = {};
    for (const message of conversations) {
        const directPartnerId = message.speaker_id === selfId ? message.listener_id
            : message.listener_id === selfId ? message.speaker_id : '';
        const key = message.final_discussion ? '__discussion__'
            : directPartnerId || `overheard:${message.speaker_id}:${message.listener_id}`;
        const label = message.final_discussion ? '终局公议'
            : directPartnerId ? (state.visible_agents?.[directPartnerId]?.display_name ||
                (message.speaker_id === directPartnerId ? message.speaker_name : message.listener_name))
                : `${message.speaker_name} / ${message.listener_name}`;
        (groups[key] ||= {key, label, messages: []}).messages.push(message);
    }
    if (!selectedConversationKey || !groups[selectedConversationKey]) {
        selectedConversationKey = Object.keys(groups)[0];
    }
    liveUi.conversationTabs.innerHTML = Object.values(groups).map(group => `
        <button type="button" data-conversation-key="${escapeHtml(group.key)}" class="${group.key === selectedConversationKey ? 'selected' : ''}">
            ${group.key === '__discussion__' ? '<span class="portrait-fallback">议</span>' : `<img src="${portraitUrl(group.label)}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'portrait-fallback',textContent:'${escapeHtml(group.label.slice(0, 1))}'}))">`}
            <strong>${escapeHtml(group.label)}</strong><small>${group.messages.length} 条</small>
        </button>`).join('');
    const active = groups[selectedConversationKey];
    liveUi.conversationThread.innerHTML = active.messages.map(message => `
        <article class="dialogue-entry ${message.speaker_id === selfId ? 'mine' : ''}">
            <img src="${portraitUrl(message.speaker_name)}" alt="${escapeHtml(message.speaker_name)}" onerror="this.style.display='none'">
            <div><span>第 ${message.round_number} 轮 · ${escapeHtml(message.speaker_name)}${message.overheard ? ' · 现场听见' : ''}</span>
            <p>${escapeHtml(message.content)}</p>${message.shared_claim ? `<em>交换情报：${escapeHtml(message.shared_claim)}</em>` : ''}</div>
        </article>`).join('');
    liveUi.conversationTabs.querySelectorAll('[data-conversation-key]').forEach(button => {
        button.addEventListener('click', () => {
            selectedConversationKey = button.dataset.conversationKey;
            renderConversationArchive(state);
        });
    });
}

function renderBulletin(state) {
    const notices = state.notices || [];
    liveUi.bulletinPosts.innerHTML = notices.length ? [...notices].reverse().map(notice => `
        <article><strong>${escapeHtml(notice.display_author)}</strong><p>${escapeHtml(notice.content)}</p><span>第 ${notice.round_number} 轮 · 已有 ${notice.seen_by?.length || 0} 人读到</span></article>
    `).join('') : '<p class="hint">公告栏还是空的。</p>';
    const canPost = Boolean(state.available_actions?.can_post_notice);
    liveUi.playerBulletinComposer.classList.toggle('hidden', viewMode !== 'player' || !canPost);
    liveUi.bulletinLocationHint.textContent = canPost ? '你正在大堂，可以实名张贴' : '前往大堂后可阅读与张贴';
}

function renderActionComposer(state) {
    const available = state.available_actions || {};
    const actor = state.self;
    const people = available.people || [];
    const inventory = available.inventory || [];
    const disabledTypes = new Set();
    if (!available.can_investigate) disabledTypes.add('investigate');
    if (!(available.moves || []).length) disabledTypes.add('move');
    if (!people.length) ['talk', 'attack'].forEach(type => disabledTypes.add(type));
    if (!inventory.length) ['hide', 'transfer'].forEach(type => disabledTypes.add(type));
    if (!people.length || !inventory.length) disabledTypes.add('transfer');
    if (!available.can_escape) disabledTypes.add('escape');
    const baseTypes = (available.types || []).filter(type => !['attack', 'treat'].includes(type));
    const baseButtons = baseTypes.map(type => `
        <button type="button" data-intent-type="${escapeHtml(type)}"
            ${disabledTypes.has(type) || !available.can_submit ? 'disabled' : ''}
            class="${selectedActionType === type && !selectedAbilityId ? 'selected' : ''} ${(available.free_action_types || []).includes(type) ? 'free-action' : ''}">
            ${escapeHtml(intentLabels[type] || type)}${(available.free_action_types || []).includes(type) ? '<small>自由</small>' : ''}
        </button>
    `).join('');
    const skillButtons = (available.special_actions || []).map(ability => `
        <button type="button" data-intent-type="${escapeHtml(ability.action_type)}" data-ability-id="${escapeHtml(ability.ability_id)}"
            title="${escapeHtml(ability.description)}"
            ${disabledTypes.has(ability.action_type) || !available.can_submit ? 'disabled' : ''}
            class="skill-action ${selectedAbilityId === ability.ability_id ? 'selected' : ''}">
            ${escapeHtml(ability.label)}<small>专属 · ?</small>
        </button>
    `).join('');
    liveUi.actionTypeGrid.innerHTML = baseButtons + skillButtons;
    liveUi.destination.innerHTML = (available.moves || []).map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');
    liveUi.target.innerHTML = people.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');
    liveUi.object.innerHTML = inventory.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');
    liveUi.memory.innerHTML = '<option value="">不交出具体记忆</option>' + (available.shareable_memories || []).map(item => `
        <option value="${escapeHtml(item.id)}">${escapeHtml(item.claim.slice(0, 70))}</option>`).join('');
    liveUi.actionTypeGrid.querySelectorAll('[data-intent-type]').forEach(button => {
        button.addEventListener('click', () => selectActionType(
            button.dataset.intentType,
            state,
            button.dataset.abilityId || null,
        ));
    });
    if (!available.can_submit) {
        selectedActionType = null;
        selectedAbilityId = null;
        liveUi.submitAction.disabled = true;
        liveUi.decisionHint.textContent = state.phase === 'discussion'
            ? '所有仍在客栈的人正在公开最后陈述；读完后再进入投票。'
            : state.phase === 'voting'
            ? '行动阶段已经结束。'
            : available.can_auto_host
                ? '没有主持人也可以继续：由你点击“自动主持”，系统会随机展开一条相关情报与事件。'
                : '主持人需要先选择本轮事件卡。';
    } else if (selectedActionType) {
        selectActionType(selectedActionType, state, selectedAbilityId);
    }
    if (!available.can_act && available.can_submit) liveUi.decisionHint.textContent = '你的角色当前无法主动行动，可以直接结束本轮。';
    if (selectedActionType === 'treat') {
        liveUi.target.innerHTML = `<option value="${escapeHtml(actor.agent_id)}">${escapeHtml(actor.display_name)}（自己）</option>` + liveUi.target.innerHTML;
    }
}

function selectActionType(type, state, abilityId = null) {
    selectedActionType = type;
    selectedAbilityId = abilityId;
    ['destinationField', 'targetField', 'objectField', 'memoryField', 'contentField']
        .forEach(key => liveUi[key].classList.add('hidden'));
    if (type === 'move') liveUi.destinationField.classList.remove('hidden');
    if (['talk', 'transfer', 'attack', 'treat'].includes(type)) liveUi.targetField.classList.remove('hidden');
    if (['transfer', 'hide'].includes(type)) liveUi.objectField.classList.remove('hidden');
    if (type === 'talk') {
        liveUi.memoryField.classList.remove('hidden');
        liveUi.contentField.classList.remove('hidden');
    }
    liveUi.actionTypeGrid.querySelectorAll('[data-intent-type]').forEach(button => {
        button.classList.toggle('selected',
            button.dataset.intentType === type
            && (button.dataset.abilityId || null) === abilityId
        );
    });
    liveUi.submitAction.disabled = !(state.available_actions?.can_submit && type);
    const isFree = (state.available_actions?.free_action_types || []).includes(type);
    liveUi.submitAction.textContent = isFree ? '确认自由行动' : '确认这次主要行动';
    liveUi.decisionHint.textContent = type === 'talk'
        ? '交谈不消耗主要行动。你可以只说一句话，也可以选择一条真实记忆交给对方。'
        : isFree
            ? '移动不消耗主要行动，也不会让其他角色凭空多行动一次。你可以充分探索客栈。'
            : `这会消耗 1 次主要行动；其余 AI 角色也会在该阶段推进自己的计划。`;
    const special = (state.available_actions?.special_actions || [])
        .find(ability => ability.ability_id === abilityId);
    if (special) liveUi.decisionHint.textContent = special.description;
}

function renderPlayerVoting(state) {
    if (!state.requires_vote) {
        liveUi.playerVotePanel.classList.add('hidden');
        return;
    }
    liveUi.playerVotePanel.classList.remove('hidden');
    liveUi.playerVoteTarget.innerHTML = (state.voting_candidates || []).map(item => `
        <option value="${escapeHtml(item.id)}">${escapeHtml(item.name)} · ${escapeHtml(item.role)}</option>`).join('');
}

function playerSyntheticState(state) {
    return {
        ...state,
        agents: state.visible_agents,
        planner: 'player',
        planner_provider: 'player',
    };
}

function receivePlayerState(state, {initial = false} = {}) {
    viewMode = 'player';
    const synthetic = playerSyntheticState(state);
    receiveState(synthetic, {initial});
    const renderKey = JSON.stringify({
        round: state.round_number,
        step: state.action_step,
        phase: state.phase,
        card: state.active_event_card,
        location: state.self.location_id,
        health: state.self.health,
        score: state.self.score,
        beliefs: state.self.beliefs?.length,
        secrets: state.known_secrets?.length,
        events: state.events?.length,
        guide: state.story_guide?.title,
        guideRecent: state.story_guide?.recent_event,
        visible: Object.keys(state.visible_agents || {}).sort(),
        objects: Object.keys(state.visible_objects || {}).sort(),
    });
    if (initial || renderKey !== lastPlayerRenderKey) {
        lastPlayerRenderKey = renderKey;
        renderPlayerPrivateState(state);
        if (liveUi.map.children.length) renderTokens(synthetic);
    }
}

function updateHeader(state) {
    liveUi.title.textContent = state.title;
    liveUi.round.textContent = state.round_number;
    liveUi.maxRounds.textContent = state.max_rounds;
    liveUi.actionStep.textContent = `主要行动 ${state.action_step || 0}/${state.actions_per_round || 3}`;
    liveUi.viewMode.textContent = viewMode === 'player'
        ? `角色视角 · ${state.self?.display_name || ''}`
        : '全局观察';
    liveUi.gameId.textContent = `局号 ${state.game_id}`;
    liveUi.planner.textContent = viewMode === 'player'
        ? '你负责本人决策 · 其余角色由 AI 驱动'
        : state.planner === 'LLMIntentPlanner'
        ? `LLM 并行决策 · ${state.planner_provider?.startsWith('ollama:') ? 'Ollama 本地' : '在线模型'}`
        : '本地规则决策';
    liveUi.status.innerHTML = `<i></i> ${state.phase === 'finished' ? '推演结束' : state.phase === 'voting' ? '等待终局投票' : state.phase === 'resolving' ? '人物正在行动' : state.active_event_card ? '等待角色行动' : '等待导演干预'}`;
}

function receiveState(state, {initial = false} = {}) {
    const previousState = liveState;
    liveState = state;
    updateHeader(state);
    renderBulletin(state);
    if (!liveUi.map.children.length) {
        Object.values(state.agents).forEach(agent => { visualLocations[agent.agent_id] = agent.location_id; });
        const unseen = state.events.slice(historyCursor);
        unseen.filter(event => event.event_type === 'move').forEach(event => {
            const actorId = event.actors?.[0];
            if (actorId && event.payload?.origin_id) visualLocations[actorId] = event.payload.origin_id;
        });
        buildMap(state);
    }
    if (!initial || historyCursor < state.events.length) {
        state.events.slice(historyCursor).forEach(event => {
            if (!queuedIds.has(event.event_id)) {
                eventQueue.push(event);
                queuedIds.add(event.event_id);
            }
        });
        drainQueue();
    }
    if (!previousState && historyCursor >= state.events.length) {
        if (viewMode !== 'player') renderTracks(state);
        renderVoting(state);
    }
}

async function pollGame() {
    if (!gameId) return;
    try {
        if (viewMode === 'player') {
            const data = await playerApi(`/api/interactive/games/${gameId}/player`);
            receivePlayerState(data.player);
        } else {
            const data = await liveApi(`/api/interactive/games/${gameId}`);
            receiveState(data.state);
        }
    } catch (error) {
        showLiveToast(error.message);
    } finally {
        pollTimer = window.setTimeout(pollGame, 900);
    }
}

async function enterLiveGame(data, {newGame = false} = {}) {
    viewMode = 'observer';
    gameId = data.state.game_id;
    window.localStorage.setItem('interactiveGameId', gameId);
    historyCursor = newGame ? 0 : Math.max(0, Number(window.localStorage.getItem(`interactiveLiveCursor:${gameId}`) || data.state.events.length));
    if (newGame) window.localStorage.setItem(`interactiveLiveCursor:${gameId}`, '0');
    liveUi.landing.classList.add('hidden');
    liveUi.playerActionColumn.classList.add('hidden');
    liveUi.observerEventPanel.classList.remove('hidden');
    liveUi.dossierEdgeTabs.classList.add('hidden');
    liveUi.app.classList.remove('hidden');
    receiveState(data.state, {initial: true});
    window.clearTimeout(pollTimer);
    pollGame();
}

async function enterPlayerGame(data, {newGame = false} = {}) {
    viewMode = 'player';
    playerToken = data.player_token || playerToken;
    gameId = data.player.game_id;
    window.localStorage.setItem('interactiveGameId', gameId);
    window.localStorage.setItem(`interactivePlayerToken:${gameId}`, playerToken);
    historyCursor = newGame
        ? 0
        : Math.max(0, Number(window.localStorage.getItem(`interactiveLiveCursor:${gameId}`) || data.player.events.length));
    if (newGame) window.localStorage.setItem(`interactiveLiveCursor:${gameId}`, '0');
    liveUi.landing.classList.add('hidden');
    if (newGame) {
        liveUi.app.classList.add('hidden');
        liveUi.dossierEdgeTabs.classList.add('hidden');
        pendingPlayerEntry = data;
        prepareOpeningDispatch(data.player);
        return;
    }
    liveUi.app.classList.remove('hidden');
    receivePlayerState(data.player, {initial: true});
    liveUi.dossierEdgeTabs.classList.remove('hidden');
    window.clearTimeout(pollTimer);
    pollGame();
}

function renderRoleOptions(scenario) {
    liveUi.roleOptions.innerHTML = (scenario.participants || []).map(role => `
        <button type="button" class="role-option" data-role-id="${escapeHtml(role.id)}">
            <strong>${escapeHtml(role.name)}</strong>
            <span>${escapeHtml(role.public_role)}</span>
            <em>以此角色进入</em>
        </button>`).join('');
    liveUi.roleOptions.querySelectorAll('[data-role-id]').forEach(button => {
        button.addEventListener('click', () => startPlayerGame(scenario.id, button.dataset.roleId, button));
    });
}

async function startPlayerGame(scenarioId, roleId, button) {
    liveUi.roleOptions.querySelectorAll('button').forEach(item => { item.disabled = true; });
    button.querySelector('em').textContent = '正在进入角色记忆……';
    try {
        const data = await liveApi('/api/interactive/games', {
            method: 'POST',
            body: JSON.stringify({
                scenario_id: scenarioId,
                player_agent_id: roleId,
                seed: Date.now() % 100000,
            }),
        });
        await enterPlayerGame(data, {newGame: true});
    } catch (error) {
        showLiveToast(error.message);
        liveUi.roleOptions.querySelectorAll('button').forEach(item => { item.disabled = false; });
        button.querySelector('em').textContent = '以此角色进入';
    }
}

async function loadLive() {
    try {
        const scenarios = await liveApi('/api/interactive/scenarios');
        const scenario = scenarios.scenarios[0];
        if (!scenario) throw new Error('没有找到可用情景');
        liveUi.premise.textContent = scenario.premise;
        liveUi.create.dataset.scenarioId = scenario.id;
        liveUi.create.disabled = false;
        renderRoleOptions(scenario);
        const savedGameId = window.localStorage.getItem('interactiveGameId');
        if (savedGameId) {
            try {
                const savedToken = window.localStorage.getItem(`interactivePlayerToken:${savedGameId}`);
                if (savedToken) {
                    playerToken = savedToken;
                    const saved = await playerApi(`/api/interactive/games/${savedGameId}/player`);
                    await enterPlayerGame({player: saved.player, player_token: savedToken});
                } else {
                    const saved = await liveApi(`/api/interactive/games/${savedGameId}`);
                    await enterLiveGame(saved);
                }
            } catch {
                window.localStorage.removeItem('interactiveGameId');
                window.localStorage.removeItem(`interactivePlayerToken:${savedGameId}`);
            }
        }
    } catch (error) {
        liveUi.premise.textContent = error.message;
    }
}

liveUi.create.addEventListener('click', async () => {
    liveUi.create.disabled = true;
    liveUi.create.textContent = '正在布置客栈……';
    try {
        const data = await liveApi('/api/interactive/games', {
            method: 'POST',
            body: JSON.stringify({scenario_id: liveUi.create.dataset.scenarioId, seed: Date.now() % 100000}),
        });
        await enterLiveGame(data, {newGame: true});
        showLiveToast('新局已建立。请打开导演台选择公开情报和第一轮事件。');
    } catch (error) {
        showLiveToast(error.message);
        liveUi.create.disabled = false;
        liveUi.create.textContent = '不选角色 · 全局观察';
    }
});

liveUi.submitAction?.addEventListener('click', async () => {
    if (!selectedActionType || !gameId) return;
    liveUi.submitAction.disabled = true;
    const submittedType = selectedActionType;
    const submittedAbilityId = selectedAbilityId;
    const submittedTarget = liveUi.target.value;
    const body = {
        action_type: selectedActionType,
        location_id: selectedActionType === 'move' ? liveUi.destination.value : null,
        target_id: ['talk', 'transfer', 'attack', 'treat'].includes(selectedActionType) ? liveUi.target.value : null,
        object_id: ['transfer', 'hide'].includes(selectedActionType) ? liveUi.object.value : null,
        share_belief_id: selectedActionType === 'talk' ? liveUi.memory.value : null,
        content: selectedActionType === 'talk' ? liveUi.content.value : '',
        ability_id: selectedAbilityId,
        reply_to_event_id: selectedActionType === 'talk' && pendingReplyEvent?.payload?.speaker_id === submittedTarget
            ? pendingReplyEvent.event_id : null,
    };
    try {
        const queued = await playerApi(`/api/interactive/games/${gameId}/player/actions`, {
            method: 'POST',
            body: JSON.stringify(body),
        });
        const result = await waitForPlayerTask(queued.task_id);
        const keepSelected = ['move', 'talk'].includes(submittedType);
        selectedActionType = keepSelected ? submittedType : null;
        selectedAbilityId = keepSelected ? submittedAbilityId : null;
        if (body.reply_to_event_id) pendingReplyEvent = null;
        liveUi.content.value = '';
        receivePlayerState(result.player);
    } catch (error) {
        showLiveToast(error.message);
        liveUi.actionProgress?.classList.add('hidden');
        liveUi.submitAction.disabled = false;
    }
});

liveUi.endPlayerRound?.addEventListener('click', async () => {
    if (!gameId) return;
    liveUi.endPlayerRound.disabled = true;
    liveUi.submitAction.disabled = true;
    try {
        const queued = await playerApi(`/api/interactive/games/${gameId}/player/end-round`, {
            method: 'POST',
            body: '{}',
        });
        const result = await waitForPlayerTask(queued.task_id);
        selectedActionType = null;
        selectedAbilityId = null;
        receivePlayerState(result.player);
        showLiveToast('本轮已经收束。准备好后，由你决定何时展开下一轮。');
    } catch (error) {
        showLiveToast(error.message);
        liveUi.endPlayerRound.disabled = false;
    }
});

liveUi.autoHostNextRound?.addEventListener('click', async () => {
    if (!gameId) return;
    liveUi.autoHostNextRound.disabled = true;
    liveUi.decisionHint.textContent = '自动主持人正在从当前局势中抽取情报与事件……';
    try {
        const data = await playerApi(`/api/interactive/games/${gameId}/player/auto-host`, {
            method: 'POST',
            body: '{}',
        });
        receivePlayerState(data.player);
        showLiveToast(data.intel ? '自动主持已发布一条情报，并展开了本轮事件。' : '自动主持已展开本轮事件。');
    } catch (error) {
        showLiveToast(error.message);
        liveUi.autoHostNextRound.disabled = false;
    }
});

liveUi.submitPlayerVote?.addEventListener('click', async () => {
    liveUi.submitPlayerVote.disabled = true;
    try {
        const queued = await playerApi(`/api/interactive/games/${gameId}/player/vote`, {
            method: 'POST',
            body: JSON.stringify({
                suspect_id: liveUi.playerVoteTarget.value,
                reason: liveUi.playerVoteReason.value,
            }),
        });
        const result = await waitForPlayerTask(queued.task_id);
        receivePlayerState(result.player);
        showLiveToast('所有人的投票已经完成，真相揭晓。');
    } catch (error) {
        showLiveToast(error.message);
        liveUi.submitPlayerVote.disabled = false;
    }
});

liveUi.enterFromDispatch?.addEventListener('click', completeOpening);
liveUi.openCharacterScroll?.addEventListener('click', () => showStoryScroll('story'));
liveUi.openMemoryScroll?.addEventListener('click', () => showStoryScroll('memory'));
liveUi.storyOverlay?.addEventListener('click', event => {
    if (event.target === liveUi.storyOverlay) hideStoryScroll();
});
liveUi.detailClose?.addEventListener('click', hideDetail);
liveUi.playerEventClose?.addEventListener('click', hidePlayerEventFeedback);
liveUi.playerEventReply?.addEventListener('click', () => {
    const event = pendingReplyEvent;
    if (!event || !liveState?.available_actions?.can_submit) return;
    hidePlayerEventFeedback();
    selectActionType('talk', liveState);
    liveUi.target.value = event.payload?.speaker_id || event.actors?.[0] || '';
    liveUi.content.placeholder = '写下你要当面回应的话……';
    liveUi.content.focus();
});
liveUi.memory?.addEventListener('change', () => {
    if (!liveUi.memory.value || liveUi.content.value.trim()) return;
    const selected = liveUi.memory.selectedOptions[0]?.textContent || '这条情报';
    liveUi.content.value = `我愿意把这条情报告诉你：${selected}`.slice(0, 200);
});
liveUi.postPlayerBulletin?.addEventListener('click', async () => {
    const content = liveUi.playerBulletinContent.value.trim();
    if (!content || !gameId) return showLiveToast('请先写下准备公开的情报。');
    liveUi.postPlayerBulletin.disabled = true;
    try {
        const data = await playerApi(`/api/interactive/games/${gameId}/player/notices`, {
            method: 'POST',
            body: JSON.stringify({content}),
        });
        liveUi.playerBulletinContent.value = '';
        receivePlayerState(data.player);
        showLiveToast('情报已经以你的名字张贴在大堂公告栏。');
    } catch (error) {
        showLiveToast(error.message);
    } finally {
        liveUi.postPlayerBulletin.disabled = false;
    }
});
liveUi.openFinalVoting?.addEventListener('click', async () => {
    if (!gameId) return;
    liveUi.openFinalVoting.disabled = true;
    try {
        const data = await playerApi(`/api/interactive/games/${gameId}/player/open-voting`, {
            method: 'POST', body: '{}',
        });
        receivePlayerState(data.player);
        liveUi.playerVotePanel.scrollIntoView({behavior: 'smooth', block: 'center'});
    } catch (error) {
        showLiveToast(error.message);
        liveUi.openFinalVoting.disabled = false;
    }
});
liveUi.detailOverlay?.addEventListener('click', event => {
    if (event.target === liveUi.detailOverlay) hideDetail();
});
document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    if (!liveUi.detailOverlay.classList.contains('hidden')) hideDetail();
    else if (!liveUi.storyOverlay.classList.contains('hidden')) hideStoryScroll();
});

loadLive();

document.getElementById('live-new-game')?.addEventListener('click', () => {
    if (gameId) window.localStorage.removeItem(`interactiveLiveCursor:${gameId}`);
    if (gameId) window.localStorage.removeItem(`interactivePlayerToken:${gameId}`);
    window.localStorage.removeItem('interactiveGameId');
    window.location.reload();
});

window.addEventListener('storage', event => {
    if (event.key === 'interactiveGameId' && event.newValue !== gameId) {
        window.location.reload();
    }
});
