"""Dependency-free Edge/CDP smoke test for the interactive map UI."""

from __future__ import annotations

import json
import os
import base64
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests
import websocket


EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
BASE_URL = (
    sys.argv[1]
    if len(sys.argv) > 1
    else os.environ.get("INTERACTIVE_BASE_URL", "http://127.0.0.1:5001")
)
DEBUG_PORT = 9331


class CdpClient:
    def __init__(self, url: str):
        self.socket = websocket.create_connection(url, timeout=10)
        self.sequence = 0
        self.exceptions: list[str] = []

    def close(self) -> None:
        self.socket.close()

    def call(self, method: str, params: dict | None = None) -> dict:
        self.sequence += 1
        request_id = self.sequence
        self.socket.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
        while True:
            message = json.loads(self.socket.recv())
            if message.get("method") == "Runtime.exceptionThrown":
                details = message.get("params", {}).get("exceptionDetails", {})
                self.exceptions.append(details.get("text", "browser exception"))
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError(message["error"])
                return message.get("result", {})

    def evaluate(self, expression: str):
        result = self.call("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        })
        if result.get("exceptionDetails"):
            raise RuntimeError(result["exceptionDetails"])
        return result.get("result", {}).get("value")


def wait_until(client: CdpClient, expression: str, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if client.evaluate(expression):
            return
        time.sleep(0.1)
    raise TimeoutError(expression)


def main() -> int:
    if not EDGE.is_file():
        raise FileNotFoundError(EDGE)
    with tempfile.TemporaryDirectory(
        prefix="agents-town-edge-", ignore_cleanup_errors=True
    ) as profile:
        process = subprocess.Popen([
            str(EDGE),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--remote-allow-origins=*",
            f"--remote-debugging-port={DEBUG_PORT}",
            f"--user-data-dir={profile}",
            "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        client = None
        try:
            deadline = time.time() + 12
            tabs = None
            while time.time() < deadline:
                try:
                    tabs = requests.get(f"http://127.0.0.1:{DEBUG_PORT}/json", timeout=.5).json()
                    if tabs:
                        break
                except requests.RequestException:
                    time.sleep(.1)
            if not tabs:
                raise RuntimeError("Edge debugging endpoint did not start")
            page = next(
                (item for item in tabs if item.get("type") == "page" and item.get("url") == "about:blank"),
                next(item for item in tabs if item.get("type") == "page"),
            )
            client = CdpClient(page["webSocketDebuggerUrl"])
            client.call("Page.enable")
            client.call("Runtime.enable")
            client.call("Emulation.setDeviceMetricsOverride", {
                "width": 1600, "height": 1100, "deviceScaleFactor": 1, "mobile": False,
            })
            client.call("Page.navigate", {"url": f"{BASE_URL}/interactive?speed=fast"})
            wait_until(client, "document.readyState === 'complete'")
            wait_until(client, "document.querySelector('#live-create') !== null")
            client.evaluate("document.querySelector('#live-create').click(); true")
            wait_until(client, "document.querySelectorAll('.agent-token').length === 6")
            wait_until(client, "[...document.querySelectorAll('.floor-art')].length === 2 && [...document.querySelectorAll('.floor-art')].every(image => image.complete && image.naturalWidth > 0)")
            first_floor = client.evaluate("""(async () => {
                const canvas = document.querySelector('.floor-stage.is-active .floor-canvas');
                const gameId = localStorage.getItem('interactiveGameId');
                const observer = gameId ? await fetch(`/api/interactive/games/${gameId}/observer`).then(response => response.json()) : {};
                return {
                    rooms: document.querySelectorAll('.live-room').length,
                    routes: new Set([...document.querySelectorAll('.map-route')].map(item => item.dataset.routeId)).size,
                    floors: document.querySelectorAll('[data-floor-target]').length,
                    tokens: document.querySelectorAll('.agent-token').length,
                    activeFloors: document.querySelectorAll('.floor-stage.is-active:not([hidden])').length,
                    canvasWidth: canvas ? Math.round(canvas.getBoundingClientRect().width) : 0,
                    canvasHeight: canvas ? Math.round(canvas.getBoundingClientRect().height) : 0,
                    fallback: document.querySelector('#live-map')?.classList.contains('map-fallback'),
                    apiHasMap: Boolean(observer.state?.map?.rooms),
                    floorArt: document.querySelectorAll('.floor-art').length,
                    floorArtLoaded: [...document.querySelectorAll('.floor-art')].filter(image => image.complete && image.naturalWidth > 0).length,
                    floorArtSources: [...document.querySelectorAll('.floor-art')].map(image => ({
                        url: image.getAttribute('src'), width: image.naturalWidth, height: image.naturalHeight,
                    })),
                    portalArt: document.querySelectorAll('.portal-art').length,
                    portalArtLoaded: [...document.querySelectorAll('.portal-art')].filter(image => image.complete && image.naturalWidth > 0).length,
                    rendererVersion: document.querySelector('#live-map')?.dataset.mapRendererVersion,
                    versionLabel: document.querySelector('.map-build-version')?.textContent.trim(),
                    portraitImages: document.querySelectorAll('.agent-token .portrait img').length,
                    portraitLoaded: [...document.querySelectorAll('.agent-token .portrait img')].filter(image => image.complete && image.naturalWidth > 0).length,
                    portraitInitials: document.querySelectorAll('.agent-token .portrait-initial').length,
                    motionPaths: document.querySelectorAll('.route-motion-path').length,
                    endpointRoutes: new Set([...document.querySelectorAll('.route-endpoint')].map(item => item.closest('.map-route')?.dataset.routeId)).size,
                    endpointCount: document.querySelectorAll('.route-endpoint').length,
                    doorEndpointImages: document.querySelectorAll('.route-mode-paired-door .route-endpoint-image, .route-mode-seam-door .route-endpoint-image').length,
                    ladderFixtureImages: document.querySelectorAll('.fixture-ladder-shaft').length,
                    sharedFixtureImages: document.querySelectorAll('.endpoint-shared .fixture-door-bay').length,
                    doorFixtureSize: (() => { const image = document.querySelector('.fixture-door-bay'); return image ? [Number(image.getAttribute('width')), Number(image.getAttribute('height'))] : null; })(),
                    ladderFixtureSize: (() => { const image = document.querySelector('.fixture-ladder-shaft'); return image ? [Number(image.getAttribute('width')), Number(image.getAttribute('height'))] : null; })(),
                    syntheticDoorShapes: document.querySelectorAll('.endpoint-door, .endpoint-seam').length,
                    roomDoorHints: document.querySelectorAll('.room-door-hint').length,
                    reachableBadges: document.querySelectorAll('.reachable-badge').length,
                    connectivityToggle: document.querySelectorAll('.connectivity-toggle').length,
                    visibleConnectors: [...document.querySelectorAll('.connector-line')].filter(path => Number(getComputedStyle(path).opacity) > .1).length,
                    syntheticPortalShapes: document.querySelectorAll('.route-mode-stairs .endpoint-shape, .route-mode-cellar-steps .endpoint-shape').length,
                };
            })()""")
            client.evaluate("document.querySelector('[data-floor-target=\"1\"]')?.click(); true")
            player_reachability = client.evaluate("""(async () => {
                const map = document.querySelector('#live-map');
                window.InteractiveMap.setInteraction(map, {
                    activeLocation: 'stable',
                    availableDestinations: ['courtyard', 'front_gate'],
                });
                await new Promise(resolve => setTimeout(resolve, 220));
                const result = {
                    reachableRoutes: new Set([...map.querySelectorAll('.map-route.is-reachable')]
                        .map(item => item.dataset.routeId)).size,
                    visibleConnectors: [...map.querySelectorAll('.floor-stage.is-active .connector-line')]
                        .filter(path => Number(getComputedStyle(path).opacity) > .1).length,
                    highlightedEndpoints: map.querySelectorAll('.map-route.is-reachable .route-endpoint').length,
                };
                window.InteractiveMap.setInteraction(map, {activeLocation: null, availableDestinations: []});
                return result;
            })()""")
            connectivity = client.evaluate("""(() => ({
                toggles: document.querySelectorAll('.connectivity-toggle').length,
                connectorLayers: document.querySelectorAll('.map-connectors').length,
                connectorLines: document.querySelectorAll('.connector-line').length,
            }))()""")
            neighbor_highlights = client.evaluate("""(() => {
                const inspect = locationId => {
                    const room = document.querySelector(`.live-room[data-location-id="${locationId}"]`);
                    room.onmouseenter();
                    const neighbors = [...document.querySelectorAll('.live-room.is-neighbor')]
                        .map(item => item.dataset.locationId).sort();
                    const routes = [...document.querySelectorAll('.map-route.is-hovered')]
                        .map(item => item.dataset.routeId).filter((value, index, values) => values.indexOf(value) === index).sort();
                    const visibleConnectors = [...document.querySelectorAll('.floor-stage.is-active .connector-line')]
                        .filter(path => Number(getComputedStyle(path).opacity) > .1).length;
                    room.onmouseleave();
                    return {neighbors, routes, visibleConnectors};
                };
                return {stable: inspect('stable'), lobby: inspect('lobby')};
            })()""")
            legacy_visual_fallback = client.evaluate("""(async () => {
                const gameId = localStorage.getItem('interactiveGameId');
                const state = (await fetch(`/api/interactive/games/${gameId}/observer`).then(response => response.json())).state;
                const legacy = structuredClone(state);
                delete legacy.map.routes.find(route => route.id === 'stable--front_gate').visual;
                const map = document.querySelector('#live-map');
                window.InteractiveMap.render(map, legacy, {});
                const result = {
                    routes: new Set([...map.querySelectorAll('.map-route')].map(item => item.dataset.routeId)).size,
                    legacyConnectors: map.querySelectorAll('.map-connector.is-legacy-connector').length,
                    visibleLegacy: [...map.querySelectorAll('.map-connector.is-legacy-connector .connector-line')]
                        .filter(path => Number(getComputedStyle(path).opacity) > .1).length,
                };
                window.InteractiveMap.render(map, state, {});
                return result;
            })()""")
            motion = client.evaluate("""(async () => {
                const gameId = localStorage.getItem('interactiveGameId');
                const state = (await fetch(`/api/interactive/games/${gameId}/observer`).then(response => response.json())).state;
                const actor = Object.values(state.agents)[0];
                const visual = Object.fromEntries(Object.values(state.agents).map(agent => [agent.agent_id, agent.location_id]));
                const sameFloorDestination = state.locations[actor.location_id].connections.find(id =>
                    state.map.rooms[id].floor === state.map.rooms[actor.location_id].floor
                );
                let sameFloorMoved = !sameFloorDestination;
                if (sameFloorDestination) {
                    await window.InteractiveMap.animateMove(document.querySelector('#live-map'), {
                        actors: [actor.agent_id],
                        payload: {origin_id: actor.location_id, destination_id: sameFloorDestination},
                    }, state, visual, {duration: 40});
                    sameFloorMoved = visual[actor.agent_id] === sameFloorDestination;
                }
                visual[actor.agent_id] = 'stairs';
                window.InteractiveMap.renderTokens(document.querySelector('#live-map'), state, visual);
                await window.InteractiveMap.animateMove(document.querySelector('#live-map'), {
                    actors: [actor.agent_id],
                    payload: {origin_id: 'stairs', destination_id: 'upper_hall'},
                }, state, visual, {duration: 40});
                return {
                    sameFloorMoved,
                    crossFloorLocation: document.querySelector(`[data-agent-id="${CSS.escape(actor.agent_id)}"]`)?.dataset.locationId,
                    activeFloor: Number(document.querySelector('.floor-stage.is-active:not([hidden])')?.dataset.floor),
                    activeRoutes: document.querySelectorAll('.map-route.is-active, .map-connector.is-active').length,
                };
            })()""")
            client.call("Emulation.setEmulatedMedia", {
                "features": [{"name": "prefers-reduced-motion", "value": "reduce"}],
            })
            reduced_motion = client.evaluate("""(async () => {
                const gameId = localStorage.getItem('interactiveGameId');
                const state = (await fetch(`/api/interactive/games/${gameId}/observer`).then(response => response.json())).state;
                const actor = Object.values(state.agents)[0];
                const visual = Object.fromEntries(Object.values(state.agents).map(agent => [agent.agent_id, agent.location_id]));
                visual[actor.agent_id] = 'stable';
                window.InteractiveMap.renderTokens(document.querySelector('#live-map'), state, visual);
                await window.InteractiveMap.animateMove(document.querySelector('#live-map'), {
                    actors: [actor.agent_id],
                    payload: {origin_id: 'stable', destination_id: 'courtyard'},
                }, state, visual, {duration: 200});
                return {
                    location: visual[actor.agent_id],
                    activeRoutes: document.querySelectorAll('.map-route.is-active, .map-connector.is-active').length,
                };
            })()""")
            client.call("Emulation.setEmulatedMedia", {"features": []})
            missing_route_fallback = client.evaluate("""(async () => {
                const gameId = localStorage.getItem('interactiveGameId');
                const source = (await fetch(`/api/interactive/games/${gameId}/observer`).then(response => response.json())).state;
                const state = {...source, map: {...source.map, routes: source.map.routes.filter(route => route.id !== 'stable--courtyard')}};
                const actor = Object.values(state.agents)[0];
                const visual = Object.fromEntries(Object.values(state.agents).map(agent => [agent.agent_id, agent.location_id]));
                visual[actor.agent_id] = 'stable';
                window.InteractiveMap.renderTokens(document.querySelector('#live-map'), state, visual);
                await window.InteractiveMap.animateMove(document.querySelector('#live-map'), {
                    actors: [actor.agent_id],
                    payload: {origin_id: 'stable', destination_id: 'courtyard'},
                }, state, visual, {duration: 40});
                return {location: visual[actor.agent_id]};
            })()""")
            client.evaluate("document.querySelector('[data-floor-target=\"2\"]')?.click(); true")
            second_floor_visible = client.evaluate(
                "!document.querySelector('.floor-stage[data-floor=\"2\"]').hidden"
            )
            second_floor_connectivity = client.evaluate("document.querySelectorAll('.floor-stage.is-active .connector-line').length")
            expected = {"rooms": 12, "routes": 13, "floors": 2, "tokens": 6, "activeFloors": 1}
            for key, value in expected.items():
                if first_floor[key] != value:
                    raise AssertionError(
                        f"{key}: expected {value}, got {first_floor[key]}; state={first_floor}"
                    )
            if first_floor["canvasWidth"] <= 0 or first_floor["canvasHeight"] <= 0:
                raise AssertionError(f"map canvas has no layout: {first_floor}")
            if first_floor["floorArt"] != 2 or first_floor["floorArtLoaded"] != 2:
                raise AssertionError(f"v002 floor art did not load: {first_floor}")
            if first_floor["portalArt"] != 0 or first_floor["portalArtLoaded"] != 0:
                raise AssertionError(f"room-scale portal art still rendered: {first_floor}")
            if first_floor["rendererVersion"] != "doors-r11" or first_floor["versionLabel"] != "连通修订 R11":
                raise AssertionError(f"R11 cache/version marker missing: {first_floor}")
            if first_floor["portraitInitials"] != 6 or first_floor["portraitLoaded"] != 6:
                raise AssertionError(f"portrait/fallback wiring failed: {first_floor}")
            for floor, art in enumerate(first_floor["floorArtSources"], start=1):
                if f"floor-{floor}-seams-r10.png" not in art["url"] or (art["width"], art["height"]) != (1536, 1024):
                    raise AssertionError(f"Wrong seam artwork or canvas dimensions: {art}")
            expected_markup = {
                "motionPaths": 14,
                "endpointRoutes": 13,
                "endpointCount": 15,
                "doorEndpointImages": 7,
                "ladderFixtureImages": 3,
                "sharedFixtureImages": 7,
                "doorFixtureSize": [44, 74],
                "ladderFixtureSize": [28, 128],
                "syntheticDoorShapes": 0,
                "roomDoorHints": 0,
                "reachableBadges": 12,
                "connectivityToggle": 0,
                "visibleConnectors": 0,
                "syntheticPortalShapes": 0,
            }
            for key, value in expected_markup.items():
                if first_floor[key] != value:
                    raise AssertionError(
                        f"{key}: expected {value}, got {first_floor[key]}; state={first_floor}"
                    )
            if player_reachability != {
                "reachableRoutes": 2,
                "visibleConnectors": 0,
                "highlightedEndpoints": 3,
            }:
                raise AssertionError(f"player reachability rendered debug connectors: {player_reachability}")
            if connectivity != {"toggles": 0, "connectorLayers": 0, "connectorLines": 0}:
                raise AssertionError(f"debug connectivity layer still exists: {connectivity}")
            painted_room_states = client.evaluate("""(() => {
                const room = document.querySelector('.has-floor-art .live-room');
                const original = room.className;
                const states = ['', 'is-current', 'active', 'is-reachable', 'is-neighbor'];
                const result = states.map(state => {
                    room.className = original + ' ' + state;
                    const style = getComputedStyle(room);
                    return {state, transform: style.transform, border: style.borderTopWidth,
                        shadow: style.boxShadow, animation: style.animationName};
                });
                room.className = original;
                return result;
            })()""")
            for state in painted_room_states:
                if any(state[key] != value for key, value in {
                    "transform": "none", "border": "0px", "shadow": "none", "animation": "none",
                }.items()):
                    raise AssertionError(f"Painted room has a card seam: {state}")
            expected_neighbors = {
                "stable": {
                    "neighbors": ["courtyard", "front_gate"],
                    "routes": ["stable--courtyard", "stable--front_gate"],
                    "visibleConnectors": 0,
                },
                "lobby": {
                    "neighbors": ["courtyard", "front_gate", "kitchen", "stairs"],
                    "routes": ["courtyard--lobby", "front_gate--lobby", "lobby--kitchen", "stairs--lobby"],
                    "visibleConnectors": 0,
                },
            }
            if neighbor_highlights != expected_neighbors:
                raise AssertionError(f"neighbor highlighting failed: {neighbor_highlights}")
            if legacy_visual_fallback != {"routes": 13, "legacyConnectors": 0, "visibleLegacy": 0}:
                raise AssertionError(f"legacy visual fallback failed: {legacy_visual_fallback}")
            if not second_floor_visible:
                raise AssertionError("second floor tab did not switch panels")
            if second_floor_connectivity != 0:
                raise AssertionError(f"second-floor debug connectors still exist: {second_floor_connectivity}")
            if motion != {
                "sameFloorMoved": True,
                "crossFloorLocation": "upper_hall",
                "activeFloor": 2,
                "activeRoutes": 0,
            }:
                raise AssertionError(f"route animation failed: {motion}")
            if reduced_motion != {"location": "courtyard", "activeRoutes": 0}:
                raise AssertionError(f"reduced-motion route fallback failed: {reduced_motion}")
            if missing_route_fallback != {"location": "courtyard"}:
                raise AssertionError(f"missing-route fallback failed: {missing_route_fallback}")
            viewport_checks = []
            for width, height in ((1600, 1100), (1280, 800), (390, 844)):
                client.call("Emulation.setDeviceMetricsOverride", {
                    "width": width,
                    "height": height,
                    "deviceScaleFactor": 1,
                    "mobile": width < 500,
                })
                time.sleep(.15)
                check = client.evaluate("""(() => {
                    const map = document.querySelector('#live-map');
                    const canvas = document.querySelector('.floor-stage.is-active .floor-canvas');
                    return {
                        mapWidth: Math.round(map.getBoundingClientRect().width),
                        canvasWidth: Math.round(canvas.getBoundingClientRect().width),
                        canvasHeight: Math.round(canvas.getBoundingClientRect().height),
                        mapOverflow: map.scrollWidth > map.clientWidth + 1,
                        activeFloors: document.querySelectorAll('.floor-stage.is-active:not([hidden])').length,
                    };
                })()""")
                if check["mapOverflow"] or check["canvasWidth"] <= 0 or check["activeFloors"] != 1:
                    raise AssertionError(f"viewport {width}x{height} failed: {check}")
                viewport_checks.append({"viewport": f"{width}x{height}", **check})
                if len(sys.argv) > 2:
                    output_path = Path(sys.argv[2])
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    for floor in (1, 2):
                        client.evaluate(f"document.querySelector('[data-floor-target=\"{floor}\"]')?.click(); true")
                        client.evaluate("document.querySelector('#live-map').scrollIntoView({block: 'center'}); true")
                        wait_until(client, "document.querySelectorAll('.agent-token .portrait img').length === 6 && [...document.querySelectorAll('.agent-token .portrait img')].every(image => image.complete && image.naturalWidth > 0)")
                        time.sleep(.2)
                        screenshot = client.call("Page.captureScreenshot", {"format": "png"})
                        output_path.with_name(f"{output_path.stem}-floor-{floor}-{width}.png").write_bytes(
                            base64.b64decode(screenshot["data"])
                        )
            if client.exceptions:
                raise AssertionError(f"browser exceptions: {client.exceptions}")
            if len(sys.argv) > 2:
                client.call("Emulation.setDeviceMetricsOverride", {
                    "width": 1600, "height": 1100, "deviceScaleFactor": 1, "mobile": False,
                })
                client.evaluate("document.querySelector('[data-floor-target=\"1\"]')?.click(); true")
                client.evaluate("document.querySelector('#live-map').scrollIntoView({block: 'center'}); true")
                screenshot = client.call("Page.captureScreenshot", {"format": "png"})
                output_path = Path(sys.argv[2])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(base64.b64decode(screenshot["data"]))
            print(json.dumps({
                **first_floor,
                **motion,
                "connectivity": connectivity,
                "playerReachability": player_reachability,
                "neighborHighlights": neighbor_highlights,
                "legacyVisualFallback": legacy_visual_fallback,
                "reducedMotion": reduced_motion,
                "missingRouteFallback": missing_route_fallback,
                "secondFloorVisible": True,
                "secondFloorConnectivity": second_floor_connectivity,
                "viewports": viewport_checks,
                "paintedRoomStates": painted_room_states,
            }, ensure_ascii=False))
            return 0
        finally:
            if client is not None:
                client.close()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
