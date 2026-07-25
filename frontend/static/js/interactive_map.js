(function () {
    const defaultColors = ['#d7a95f', '#81a18e', '#c27868', '#8d9fc7', '#b994c1', '#d0b878'];

    function escapeHtml(value) {
        return String(value ?? '').replace(/[&<>"']/g, character => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;',
        })[character]);
    }

    function floorLabel(floor) {
        return Number(floor) === 1
            ? '一层 · 大堂、后院与正门'
            : '二层 · 客房与回廊';
    }

    function renderStructure(container, state) {
        const byFloor = Object.values(state.locations || {}).reduce((result, location) => {
            const floor = Number(location.layout?.floor || 1);
            (result[floor] ||= []).push(location);
            return result;
        }, {});
        container.innerHTML = Object.entries(byFloor)
            .sort(([left], [right]) => Number(left) - Number(right))
            .map(([floor, locations]) => {
                const rooms = locations.map(location => {
                    const layout = location.layout || {x: 1, y: 1, w: 1, h: 1};
                    const unread = location.id === 'lobby' && state.bulletin?.has_unread;
                    return `<article class="live-room ${unread ? 'has-unread-bulletin' : ''}" data-location-id="${escapeHtml(location.id)}" style="grid-column:${layout.x} / span ${layout.w};grid-row:${layout.y} / span ${layout.h}">
                        <div class="room-name"><span>${escapeHtml(location.name)}${unread ? '<b class="bulletin-unread">新公告</b>' : ''}</span><small>${location.public ? '公开' : '隐蔽'}</small></div>
                        <div class="room-description">${escapeHtml(location.description)}</div>
                        <div class="token-layer"></div>
                    </article>`;
                }).join('');
                return `<section class="floor-stage">
                    <div class="floor-label">${floorLabel(floor)}</div>
                    <div class="floor-grid">${rooms}</div>
                </section>`;
            }).join('');
    }

    function renderTokens(container, state, visualLocations = {}, colors = defaultColors) {
        container.querySelectorAll('.token-layer').forEach(layer => { layer.innerHTML = ''; });
        Object.values(state.agents || {}).forEach((agent, index) => {
            const locationId = visualLocations[agent.agent_id] || agent.location_id;
            const layer = container.querySelector(
                `[data-location-id="${CSS.escape(locationId)}"] .token-layer`
            );
            if (!layer) return;
            const token = document.createElement('div');
            token.className = 'agent-token';
            token.dataset.agentId = agent.agent_id;
            token.style.setProperty('--agent-color', colors[index % colors.length]);
            token.innerHTML = `<span class="portrait">${escapeHtml(agent.display_name.slice(0, 1))}</span><span>${escapeHtml(agent.display_name)}</span>`;
            layer.appendChild(token);
        });
    }

    function render(container, state, options = {}) {
        renderStructure(container, state);
        renderTokens(container, state, options.visualLocations, options.colors);
    }

    window.InteractiveMap = {
        colors: defaultColors,
        render,
        renderTokens,
    };
}());
