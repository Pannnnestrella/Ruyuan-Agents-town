(function () {
    const defaultColors = ['#d7a95f', '#81a18e', '#c27868', '#8d9fc7', '#b994c1', '#d0b878'];
    const rendererVersion = 'doors-r11';

    function escapeHtml(value) {
        return String(value ?? '').replace(/[&<>"']/g, character => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;',
        })[character]);
    }

    function floorLabel(floor) {
        return Number(floor) === 1 ? '一层 · 大堂、后院与正门' : '二层 · 客房与回廊';
    }

    function pointPath(points) {
        return (points || []).map((point, index) => `${index ? 'L' : 'M'} ${point[0]} ${point[1]}`).join(' ');
    }

    function rectStyle(rect, grid) {
        return [
            `left:${((rect.x - 1) / grid.columns) * 100}%`,
            `top:${((rect.y - 1) / grid.rows) * 100}%`,
            `width:${(rect.w / grid.columns) * 100}%`,
            `height:${(rect.h / grid.rows) * 100}%`,
        ].join(';');
    }

    function renderFallbackStructure(container, state) {
        const byFloor = Object.values(state.locations || {}).reduce((result, location) => {
            const floor = Number(location.layout?.floor || 1);
            (result[floor] ||= []).push(location);
            return result;
        }, {});
        container.classList.add('map-fallback');
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
                return `<section class="floor-stage is-active" data-floor="${floor}">
                    <div class="floor-label">${floorLabel(floor)}</div>
                    <div class="floor-grid">${rooms}</div>
                </section>`;
            }).join('');
    }

    function portPoint(binding, port) {
        if (!port) return null;
        if (port.edge === 'interior') {
            return Array.isArray(port.point) && port.point.length === 2
                ? {x: Number(port.point[0]), y: Number(port.point[1])} : null;
        }
        const room = binding.rooms?.[port.room];
        if (!room?.rect) return null;
        const tile = Number(binding.grid.tile_size);
        const left = (room.rect.x - 1) * tile;
        const top = (room.rect.y - 1) * tile;
        const width = room.rect.w * tile;
        const height = room.rect.h * tile;
        const offset = Number(port.offset || 0);
        if (port.edge === 'left') return {x: left, y: top + offset * height};
        if (port.edge === 'right') return {x: left + width, y: top + offset * height};
        if (port.edge === 'top') return {x: left + offset * width, y: top};
        if (port.edge === 'bottom') return {x: left + offset * width, y: top + height};
        return null;
    }

    function fixtureAsset(binding, mode, fallbackAsset) {
        if (mode === 'paired-door' || mode === 'seam-door') {
            return binding.connection_fixtures?.same_floor || fallbackAsset || '';
        }
        if (mode === 'stairs' || mode === 'cellar-steps') {
            return binding.connection_fixtures?.cross_floor || '';
        }
        return fallbackAsset || '';
    }

    function endpointSymbol(binding, mode, asset) {
        const fixture = fixtureAsset(binding, mode, asset);
        if (mode === 'paired-door' || mode === 'seam-door') {
            return fixture ? `<image class="route-endpoint-image fixture-door-bay" href="${escapeHtml(fixture)}" x="-22" y="-74" width="44" height="74" preserveAspectRatio="xMidYMax meet"></image>` : '';
        }
        if (mode === 'covered-passage') {
            return '<path class="endpoint-shape endpoint-passage" d="M -13 10 V -3 Q 0 -18 13 -3 V 10 M -16 10 H 16 M -12 -7 H 12"></path>';
        }
        if (mode === 'cellar-steps') {
            return fixture ? `<image class="route-endpoint-image fixture-ladder-shaft" href="${escapeHtml(fixture)}" x="-14" y="-64" width="28" height="128" preserveAspectRatio="xMidYMid slice"></image>` : '';
        }
        if (mode === 'stairs') {
            return fixture ? `<image class="route-endpoint-image fixture-ladder-shaft" href="${escapeHtml(fixture)}" x="-14" y="-64" width="28" height="128" preserveAspectRatio="xMidYMid slice"></image>` : '';
        }
        return '<circle class="endpoint-shape endpoint-generic" r="7"></circle>';
    }

    function sharedFixturePoint(binding, route, floor) {
        if (!['paired-door', 'seam-door', 'cellar-steps'].includes(route.visual?.mode)) return null;
        const fromRoom = binding.rooms?.[route.ports?.from?.room];
        const toRoom = binding.rooms?.[route.ports?.to?.room];
        if (!fromRoom || !toRoom || Number(fromRoom.floor) !== Number(floor.id) || Number(toRoom.floor) !== Number(floor.id)) return null;
        const declaredPoint = route.visual?.shared_fixture_point;
        if (Array.isArray(declaredPoint) && declaredPoint.length === 2) {
            return {x: Number(declaredPoint[0]), y: Number(declaredPoint[1])};
        }
        const tile = Number(binding.grid.tile_size);
        const fromBounds = {
            left: (fromRoom.rect.x - 1) * tile, top: (fromRoom.rect.y - 1) * tile,
            right: (fromRoom.rect.x - 1 + fromRoom.rect.w) * tile, bottom: (fromRoom.rect.y - 1 + fromRoom.rect.h) * tile,
        };
        const toBounds = {
            left: (toRoom.rect.x - 1) * tile, top: (toRoom.rect.y - 1) * tile,
            right: (toRoom.rect.x - 1 + toRoom.rect.w) * tile, bottom: (toRoom.rect.y - 1 + toRoom.rect.h) * tile,
        };
        if (route.visual?.mode === 'cellar-steps') {
            if (fromBounds.bottom === toBounds.top || toBounds.bottom === fromBounds.top) {
                const left = Math.max(fromBounds.left, toBounds.left);
                const right = Math.min(fromBounds.right, toBounds.right);
                if (right > left) return {x: (left + right) / 2, y: fromBounds.bottom === toBounds.top ? fromBounds.bottom : toBounds.bottom};
            }
        }
        const from = portPoint(binding, route.ports.from);
        const to = portPoint(binding, route.ports.to);
        if (!from || !to) return null;
        const distance = Math.hypot(to.x - from.x, to.y - from.y);
        const maximum = Number(binding.connection_fixtures?.shared_span_max || 0);
        if (!maximum || distance > maximum) return null;
        return {x: (from.x + to.x) / 2, y: (from.y + to.y) / 2};
    }

    function endpointMarkup(binding, route, floor) {
        const visual = route.visual;
        if (!visual?.mode) return '';
        const sharedPoint = sharedFixturePoint(binding, route, floor);
        if (sharedPoint) {
            const label = visual.label || '入口';
            return `<g class="route-endpoint endpoint-shared endpoint-${escapeHtml(visual.mode)}"
                data-endpoint-location="${escapeHtml(route.from)} ${escapeHtml(route.to)}" data-endpoint-role="shared"
                transform="translate(${sharedPoint.x} ${sharedPoint.y})" role="img" aria-label="${escapeHtml(label)}">
                <g class="endpoint-symbol shared-connector-bay">
                    <circle class="endpoint-halo" r="19"></circle>
                    ${visual.render_fixture === false ? '' : endpointSymbol(binding, visual.mode, visual.endpoint_asset || '')}
                    <text class="route-endpoint-label" text-anchor="middle" x="0" y="${visual.render_fixture === false ? -25 : ['paired-door', 'seam-door'].includes(visual.mode) ? -80 : -118}">${escapeHtml(label)}</text>
                </g>
            </g>`;
        }
        const roles = visual.mode === 'seam-door' ? ['from'] : ['from', 'to'];
        return roles.map(role => {
            const port = route.ports?.[role];
            const room = binding.rooms?.[port?.room];
            if (!room || Number(room.floor) !== Number(floor.id)) return '';
            const fixturePoint = visual.fixture_points?.[role];
            const point = Array.isArray(fixturePoint) && fixturePoint.length === 2
                ? {x: Number(fixturePoint[0]), y: Number(fixturePoint[1])}
                : portPoint(binding, port);
            if (!point) return '';
            const insetX = point.x <= 0 ? 22 : point.x >= binding.grid.width ? -22 : 0;
            const insetY = point.y <= 0 ? 17 : point.y >= binding.grid.height ? -17 : 0;
            const asset = visual.endpoint_assets?.[role] || visual.endpoint_asset || '';
            const label = visual.label || '入口';
            return `<g class="route-endpoint endpoint-${escapeHtml(role)} endpoint-${escapeHtml(visual.mode)}"
                data-endpoint-location="${escapeHtml(port.room)}" data-endpoint-role="${escapeHtml(role)}"
                ${asset ? `data-endpoint-asset="${escapeHtml(asset)}"` : ''}
                transform="translate(${point.x} ${point.y})" role="img" aria-label="${escapeHtml(label)}">
                <g class="endpoint-symbol" transform="translate(${insetX} ${insetY})">
                    <circle class="endpoint-halo" r="17"></circle>
                    ${endpointSymbol(binding, visual.mode, asset)}
                    <text class="route-endpoint-label" text-anchor="middle" x="0" y="-25">${escapeHtml(label)}</text>
                </g>
            </g>`;
        }).join('');
    }

    function motionPathMarkup(route, segment) {
        return `<path class="route-motion-path" d="${pointPath(segment.points)}"></path>`;
    }

    function connectorMarkup(route, segment) {
        const visual = route.visual;
        if (visual?.mode === 'seam-door' || visual?.show_overview_path === false) return '';
        const legacy = !visual?.mode;
        return `<g class="map-connector connector-${escapeHtml(visual?.mode || route.kind || 'legacy')} ${legacy ? 'is-legacy-connector' : ''}"
            data-route-id="${escapeHtml(route.id)}" data-from="${escapeHtml(route.from)}" data-to="${escapeHtml(route.to)}">
            <path class="connector-shadow" d="${pointPath(segment.points)}"></path>
            <path class="connector-line" d="${pointPath(segment.points)}"></path>
        </g>`;
    }

    function connectorsMarkup(binding, floor) {
        return (binding.routes || []).flatMap(route =>
            (route.segments || [])
                .filter(segment => Number(segment.floor) === Number(floor.id))
                .map(segment => connectorMarkup(route, segment))
        ).join('');
    }

    function routeMarkup(binding, floor) {
        return (binding.routes || []).flatMap(route =>
            (route.segments || []).filter(segment => Number(segment.floor) === Number(floor.id)).map(segment => {
                const mode = route.visual?.mode || 'legacy';
                return `<g class="map-route route-${escapeHtml(route.kind)} route-mode-${escapeHtml(mode)}"
                    data-route-id="${escapeHtml(route.id)}" data-from="${escapeHtml(route.from)}" data-to="${escapeHtml(route.to)}"
                    data-visual-mode="${escapeHtml(mode)}">
                    ${motionPathMarkup(route, segment)}
                    ${endpointMarkup(binding, route, floor)}
                </g>`;
            })
        ).join('');
    }

    function decorationMarkup(binding, floor) {
        return (binding.decorations || []).filter(item => Number(item.floor) === Number(floor.id)).map(item => `
            <div class="map-decoration decoration-${escapeHtml(item.kind)}" style="${rectStyle(item.rect, binding.grid)}">
                <span>${escapeHtml(item.label || '')}</span>
            </div>`).join('');
    }

    function portalArtMarkup(binding, floor) {
        return (binding.asset_manifest?.assets || [])
            .filter(asset => asset.kind === 'portal' && asset.render_independent !== false)
            .map(asset => {
                const room = asset.room_id ? binding.rooms?.[asset.room_id] : null;
                const assetFloor = Number(asset.floor || room?.floor);
                const rect = asset.rect || room?.rect;
                if (assetFloor !== Number(floor.id) || !rect || !asset.source) return '';
                const source = `/static/assets/maps/guangling_inn/v002/${encodeURIComponent(asset.source)}?v=${rendererVersion}`;
                return `<img class="portal-art portal-art-${escapeHtml(asset.id)}" data-portal-id="${escapeHtml(asset.id)}"
                    src="${escapeHtml(source)}" alt="" draggable="false" style="${rectStyle(rect, binding.grid)}">`;
            }).join('');
    }

    function roomMarkup(binding, state, floor) {
        return Object.entries(binding.rooms || {})
            .filter(([, room]) => Number(room.floor) === Number(floor.id))
            .map(([locationId, room]) => {
                const location = state.locations?.[locationId] || {id: locationId, name: locationId};
                const unread = locationId === 'lobby' && state.bulletin?.has_unread;
                return `<article class="live-room room-${escapeHtml(room.theme || 'default')} ${unread ? 'has-unread-bulletin' : ''}"
                    data-location-id="${escapeHtml(locationId)}" data-floor="${floor.id}" tabindex="0" role="button"
                    aria-label="${escapeHtml(location.name)}。${escapeHtml(location.description || '')}" style="${rectStyle(room.rect, binding.grid)}">
                    <div class="room-name"><span>${escapeHtml(location.name)}${unread ? '<b class="bulletin-unread">新公告</b>' : ''}</span><small>${location.public ? '公开' : '隐蔽'}</small></div>
                    <div class="room-description">${escapeHtml(location.description || '')}</div>
                    <span class="reachable-badge" aria-hidden="true">可达</span>
                </article>`;
            }).join('');
    }

    function renderBoundStructure(container, state, options) {
        const binding = state.map;
        const activeLocation = options.activeLocation || state.self?.location_id || Object.values(state.agents || {})[0]?.location_id;
        const initialFloor = binding.rooms?.[activeLocation]?.floor || binding.floors?.[0]?.id || 1;
        container.classList.remove('map-fallback');
        container.dataset.mapRendererVersion = rendererVersion;
        container.innerHTML = `
            <div class="map-toolbar">
                <div class="floor-tabs" role="tablist" aria-label="客栈楼层">
                    ${(binding.floors || []).map(floor => `<button type="button" role="tab" data-floor-target="${floor.id}">
                        <strong>${escapeHtml(floor.name)}</strong><span>${escapeHtml(floor.subtitle || '')}</span><b class="floor-count">0 人</b>
                    </button>`).join('')}
                </div>
                <div class="map-tools">
                    <span class="map-build-version" title="Map renderer ${rendererVersion}">&#36830;&#36890;&#20462;&#35746; R11</span>
                    <div class="map-legend"><span class="legend-endpoint">出口</span><span class="legend-reachable">当前可达</span><span class="legend-stairs">跨层</span></div>
                </div>
            </div>
            <div class="map-viewport">
                ${(binding.floors || []).map(floor => `<section class="floor-stage" data-floor="${floor.id}" role="tabpanel">
                    <div class="floor-label"><strong>${escapeHtml(floor.name)}</strong><span>${escapeHtml(floor.subtitle || '')}</span></div>
                    <div class="floor-canvas ${floor.art ? 'has-floor-art' : ''}" style="aspect-ratio:${binding.grid.width}/${binding.grid.height}">
                        ${floor.art ? `<img class="floor-art" src="${escapeHtml(floor.art)}" alt="" draggable="false">` : ''}
                        <div class="portal-art-layer">${portalArtMarkup(binding, floor)}</div>
                        <svg class="map-routes" viewBox="0 0 ${binding.grid.width} ${binding.grid.height}" preserveAspectRatio="none" aria-label="地点连通路线">
                            ${routeMarkup(binding, floor)}
                        </svg>
                        <div class="decoration-layer">${decorationMarkup(binding, floor)}</div>
                        <div class="room-layer">${roomMarkup(binding, state, floor)}</div>
                        <div class="token-layer floor-token-layer" data-token-floor="${floor.id}"></div>
                    </div>
                </section>`).join('')}
            </div>`;
        container._interactiveMap = {state, options: {...options}, activeFloor: Number(initialFloor), overview: false};
        container.querySelectorAll('[data-floor-target]').forEach(button => {
            button.addEventListener('click', () => showFloor(container, Number(button.dataset.floorTarget)));
        });
        showFloor(container, initialFloor);
        setInteraction(container, options);
    }

    function clearActiveRoutes(container) {
        container.querySelectorAll('.map-route.is-active, .map-connector.is-active').forEach(route => {
            route.classList.remove('is-active');
        });
    }

    function setOverview(container, enabled) {
        const model = container._interactiveMap;
        if (!model) return;
        model.overview = false;
        container.classList.remove('show-connectivity');
    }

    function showFloor(container, floor) {
        const model = container._interactiveMap;
        if (!model || !container.querySelector('.map-viewport')) return;
        clearActiveRoutes(container);
        model.activeFloor = Number(floor);
        container.querySelectorAll('.floor-stage').forEach(stage => {
            const active = Number(stage.dataset.floor) === model.activeFloor;
            stage.classList.toggle('is-active', active);
            stage.hidden = !active;
        });
        container.querySelectorAll('[data-floor-target]').forEach(button => {
            const active = Number(button.dataset.floorTarget) === model.activeFloor;
            button.classList.toggle('is-active', active);
            button.setAttribute('aria-selected', String(active));
        });
    }

    function routeFor(binding, origin, destination) {
        return (binding?.routes || []).find(route =>
            (route.from === origin && route.to === destination)
            || (route.from === destination && route.to === origin)
        );
    }

    function routeElements(container, routeId) {
        return container.querySelectorAll(
            `.map-route[data-route-id="${CSS.escape(routeId)}"], .map-connector[data-route-id="${CSS.escape(routeId)}"]`
        );
    }

    function clearRelatedHighlight(container) {
        container.classList.remove('has-map-focus');
        container.querySelectorAll('.is-hovered, .is-neighbor, .is-focused-room').forEach(element => {
            element.classList.remove('is-hovered', 'is-neighbor', 'is-focused-room');
        });
    }

    function highlightRelated(container, locationId, enabled) {
        if (!locationId) return;
        if (!enabled) {
            clearRelatedHighlight(container);
            return;
        }
        clearRelatedHighlight(container);
        container.classList.add('has-map-focus');
        container.querySelector(`.live-room[data-location-id="${CSS.escape(locationId)}"]`)?.classList.add('is-focused-room');
        container.querySelectorAll('.map-route').forEach(route => {
            if (route.dataset.from === locationId || route.dataset.to === locationId) {
                routeElements(container, route.dataset.routeId).forEach(element => element.classList.add('is-hovered'));
                const other = route.dataset.from === locationId ? route.dataset.to : route.dataset.from;
                container.querySelector(`.live-room[data-location-id="${CSS.escape(other)}"]`)?.classList.add('is-neighbor');
            }
        });
    }

    function setInteraction(container, options = {}) {
        const model = container._interactiveMap;
        if (!model) return;
        model.options = {...model.options, ...options};
        const available = new Set(model.options.availableDestinations || []);
        const active = model.options.activeLocation || null;
        container.querySelectorAll('.live-room').forEach(room => {
            const locationId = room.dataset.locationId;
            const reachable = available.has(locationId);
            room.classList.toggle('is-current', locationId === active);
            room.classList.toggle('is-reachable', reachable);
            room.setAttribute('aria-disabled', String(!reachable));
            room.onclick = reachable && model.options.onSelectLocation
                ? () => model.options.onSelectLocation(locationId) : null;
            room.onkeydown = reachable && model.options.onSelectLocation
                ? event => {
                    if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        model.options.onSelectLocation(locationId);
                    }
                } : null;
            room.onmouseenter = () => highlightRelated(container, locationId, true);
            room.onmouseleave = () => highlightRelated(container, locationId, false);
            room.onfocus = () => highlightRelated(container, locationId, true);
            room.onblur = () => highlightRelated(container, locationId, false);
        });
        container.querySelectorAll('.map-route').forEach(route => {
            const endpoints = [route.dataset.from, route.dataset.to];
            const reachable = active && endpoints.includes(active)
                && endpoints.some(endpoint => available.has(endpoint));
            routeElements(container, route.dataset.routeId).forEach(element => {
                element.classList.toggle('is-reachable', Boolean(reachable));
            });
        });
        if (active && model.state.map?.rooms?.[active]) {
            showFloor(container, model.state.map.rooms[active].floor);
        }
    }

    function tokenPoint(binding, locationId, index) {
        const room = binding.rooms[locationId];
        const rect = room.rect;
        const tile = binding.grid.tile_size;
        const columns = Math.max(1, room.token_grid?.columns || 1);
        const rows = Math.max(1, room.token_grid?.rows || 1);
        const column = index % columns;
        const row = Math.min(rows - 1, Math.floor(index / columns));
        const left = (rect.x - 1) * tile;
        const top = (rect.y - 1) * tile;
        const width = rect.w * tile;
        const height = rect.h * tile;
        const tokenTop = top + Math.min(48, height * .34);
        const tokenHeight = Math.max(34, height - Math.min(54, height * .4));
        return {x: left + ((column + .5) / columns) * width, y: tokenTop + ((row + .5) / rows) * tokenHeight};
    }

    function tokenElement(agent, color) {
        const token = document.createElement('div');
        token.className = 'agent-token';
        token.dataset.agentId = agent.agent_id;
        token.style.setProperty('--agent-color', color);
        const portrait = `/static/common/characters/${encodeURIComponent(agent.display_name)}/portrait.png`;
        token.innerHTML = `<span class="portrait" aria-hidden="true"><span class="portrait-initial">${escapeHtml(agent.display_name.slice(0, 1))}</span><img src="${escapeHtml(portrait)}" alt="" onerror="this.remove()"></span><span class="token-name">${escapeHtml(agent.display_name)}</span>`;
        return token;
    }

    function renderBoundTokens(container, state, visualLocations, colors) {
        const binding = state.map;
        container.querySelectorAll('.floor-token-layer').forEach(layer => { layer.innerHTML = ''; });
        const agents = Object.values(state.agents || {}).sort((left, right) => left.agent_id.localeCompare(right.agent_id, 'zh-CN'));
        const byLocation = agents.reduce((result, agent) => {
            const locationId = visualLocations[agent.agent_id] || agent.location_id;
            (result[locationId] ||= []).push(agent);
            return result;
        }, {});
        Object.entries(byLocation).forEach(([locationId, occupants]) => {
            const room = binding.rooms?.[locationId];
            if (!room) return;
            const layer = container.querySelector(`[data-token-floor="${room.floor}"]`);
            occupants.forEach((agent, index) => {
                const sourceIndex = agents.findIndex(item => item.agent_id === agent.agent_id);
                const token = tokenElement(agent, colors[sourceIndex % colors.length]);
                const point = tokenPoint(binding, locationId, index);
                token.dataset.locationId = locationId;
                token.style.left = `${point.x / binding.grid.width * 100}%`;
                token.style.top = `${point.y / binding.grid.height * 100}%`;
                layer.appendChild(token);
            });
        });
        (binding.floors || []).forEach(floor => {
            const count = agents.filter(agent => {
                const locationId = visualLocations[agent.agent_id] || agent.location_id;
                return Number(binding.rooms?.[locationId]?.floor) === Number(floor.id);
            }).length;
            const label = container.querySelector(`[data-floor-target="${floor.id}"] .floor-count`);
            if (label) label.textContent = `${count} 人`;
        });
    }

    function renderFallbackTokens(container, state, visualLocations, colors) {
        container.querySelectorAll('.token-layer').forEach(layer => { layer.innerHTML = ''; });
        Object.values(state.agents || {}).forEach((agent, index) => {
            const locationId = visualLocations[agent.agent_id] || agent.location_id;
            const layer = container.querySelector(`[data-location-id="${CSS.escape(locationId)}"] .token-layer`);
            if (!layer) return;
            layer.appendChild(tokenElement(agent, colors[index % colors.length]));
        });
    }

    function renderTokens(container, state, visualLocations = {}, colors = defaultColors) {
        if (state.map?.rooms) renderBoundTokens(container, state, visualLocations, colors);
        else renderFallbackTokens(container, state, visualLocations, colors);
    }

    function render(container, state, options = {}) {
        if (state.map?.rooms) renderBoundStructure(container, state, options);
        else renderFallbackStructure(container, state);
        renderTokens(container, state, options.visualLocations || {}, options.colors || defaultColors);
    }

    async function animateFallback(container, actorId, destination, state, visualLocations, colors, duration) {
        const token = container.querySelector(`[data-agent-id="${CSS.escape(actorId)}"]`);
        const before = token?.getBoundingClientRect();
        visualLocations[actorId] = destination;
        renderTokens(container, state, visualLocations, colors);
        const moved = container.querySelector(`[data-agent-id="${CSS.escape(actorId)}"]`);
        const after = moved?.getBoundingClientRect();
        if (!before || !after || !moved) return;
        await moved.animate([
            {transform: `translate(${before.left - after.left}px, ${before.top - after.top}px) translate(-50%, -50%)`, zIndex: 30},
            {transform: 'translate(-50%, -50%)', zIndex: 30},
        ], {duration, easing: 'cubic-bezier(.2,.78,.25,1)'}).finished.catch(() => {});
    }

    function animationFrames(path, reverse, token, canvas, binding, destinationPoint, fadeOut = false) {
        const length = path.getTotalLength();
        const tokenBox = token.getBoundingClientRect();
        const canvasBox = canvas.getBoundingClientRect();
        const startX = tokenBox.left + tokenBox.width / 2 - canvasBox.left;
        const startY = tokenBox.top + tokenBox.height / 2 - canvasBox.top;
        const frames = [{transform: 'translate(-50%, -50%)', opacity: 1}];
        for (let index = 1; index <= 12; index += 1) {
            const progress = index / 12;
            const point = path.getPointAtLength(length * (reverse ? 1 - progress : progress));
            const x = point.x / binding.grid.width * canvasBox.width;
            const y = point.y / binding.grid.height * canvasBox.height;
            frames.push({
                transform: `translate(calc(-50% + ${x - startX}px), calc(-50% + ${y - startY}px))`,
                opacity: fadeOut ? Math.max(0, 1 - progress * .9) : 1,
            });
        }
        if (destinationPoint) {
            const x = destinationPoint.x / binding.grid.width * canvasBox.width;
            const y = destinationPoint.y / binding.grid.height * canvasBox.height;
            frames.push({transform: `translate(calc(-50% + ${x - startX}px), calc(-50% + ${y - startY}px))`, opacity: fadeOut ? 0 : 1});
        }
        return frames;
    }

    async function animateMove(container, event, state, visualLocations = {}, options = {}) {
        const actorId = event.actors?.[0];
        const destination = event.payload?.destination_id || event.state_changes?.find(change => change.agent_id === actorId)?.location_id;
        const origin = event.payload?.origin_id || visualLocations[actorId];
        if (!actorId || !destination) return;
        const colors = options.colors || defaultColors;
        const duration = Number(options.duration || 780);
        const binding = state.map;
        const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
        if (!binding?.rooms || !origin || reduced) {
            await animateFallback(container, actorId, destination, state, visualLocations, colors, reduced ? 0 : duration);
            return;
        }
        const route = routeFor(binding, origin, destination);
        if (!route) {
            await animateFallback(container, actorId, destination, state, visualLocations, colors, duration);
            return;
        }
        const originFloor = binding.rooms[origin]?.floor;
        const destinationFloor = binding.rooms[destination]?.floor;
        showFloor(container, originFloor);
        const token = container.querySelector(`[data-agent-id="${CSS.escape(actorId)}"]`);
        const originStage = container.querySelector(`.floor-stage[data-floor="${originFloor}"]`);
        const path = originStage?.querySelector(`[data-route-id="${CSS.escape(route.id)}"] .route-motion-path`);
        const canvas = originStage?.querySelector('.floor-canvas');
        if (!token || !path || !canvas) {
            await animateFallback(container, actorId, destination, state, visualLocations, colors, duration);
            return;
        }
        const reverse = route.to === origin;
        const crossesFloor = Number(originFloor) !== Number(destinationFloor);
        const destinationAgents = Object.values(state.agents || {}).filter(agent => agent.location_id === destination)
            .sort((left, right) => left.agent_id.localeCompare(right.agent_id, 'zh-CN'));
        const destinationIndex = Math.max(0, destinationAgents.findIndex(agent => agent.agent_id === actorId));
        const targetPoint = crossesFloor ? null : tokenPoint(binding, destination, destinationIndex);
        const activeRoutes = routeElements(container, route.id);
        activeRoutes.forEach(item => item.classList.add('is-active'));
        await token.animate(
            animationFrames(path, reverse, token, canvas, binding, targetPoint, crossesFloor),
            {duration: crossesFloor ? duration * .55 : duration, easing: 'cubic-bezier(.2,.78,.25,1)', fill: 'forwards'}
        ).finished.catch(() => {});
        visualLocations[actorId] = destination;
        activeRoutes.forEach(item => item.classList.remove('is-active'));
        showFloor(container, destinationFloor);
        renderTokens(container, state, visualLocations, colors);
        if (crossesFloor) {
            const arrived = container.querySelector(`[data-agent-id="${CSS.escape(actorId)}"]`);
            await arrived?.animate([{opacity: 0, transform: 'translate(-50%, -65%)'}, {opacity: 1, transform: 'translate(-50%, -50%)'}], {
                duration: duration * .45, easing: 'ease-out',
            }).finished.catch(() => {});
        }
    }

    window.InteractiveMap = {
        colors: defaultColors,
        version: rendererVersion,
        render,
        renderTokens,
        setInteraction,
        setOverview,
        showFloor,
        routeFor,
        portPoint,
        animateMove,
    };
}());
