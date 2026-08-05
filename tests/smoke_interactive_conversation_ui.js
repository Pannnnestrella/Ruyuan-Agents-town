const { chromium } = require('playwright');

(async () => {
    const baseUrl = process.env.INTERACTIVE_BASE_URL || 'http://127.0.0.1:5001';
    const executablePath = process.env.INTERACTIVE_BROWSER_EXECUTABLE || undefined;
    const browser = await chromium.launch({
        headless: true,
        executablePath,
        args: ['--no-sandbox', '--disable-gpu'],
        timeout: 15000,
    });
    const context = await browser.newContext({viewport: {width: 1500, height: 1000}});
    const errors = [];
    const watch = page => {
        page.on('pageerror', error => errors.push(`pageerror: ${error.message}`));
        page.on('console', message => {
            if (message.type() === 'error') errors.push(`console: ${message.text()}`);
        });
        page.on('response', response => {
            if (response.status() >= 400) errors.push(`response: ${response.status()} ${response.url()}`);
        });
    };
    try {
        const live = await context.newPage();
        watch(live);
        await live.goto(`${baseUrl}/interactive?speed=fast`, {waitUntil: 'networkidle'});
        await live.evaluate(() => localStorage.clear());
        await live.reload({waitUntil: 'networkidle'});
        await live.locator('[data-role-id="广陵王"]').click();
        await live.locator('#enter-from-dispatch').click();
        await live.locator('#story-overlay:not(.hidden)').waitFor();
        await live.locator('#story-overlay').click({position: {x: 5, y: 5}});
        await live.locator('#story-overlay').waitFor({state: 'hidden'});
        await live.waitForFunction(() => document.querySelector('#live-round-timer-state')?.textContent === '本轮探索');

        const gameId = (await live.locator('#live-game-id').textContent()).replace('局号 ', '').trim();
        const publicState = await live.evaluate(async ({baseUrl, gameId}) => {
            const response = await fetch(`${baseUrl}/api/interactive/games/${gameId}`);
            return (await response.json()).state;
        }, {baseUrl, gameId});
        const player = publicState.agents['广陵王'];
        const target = Object.values(publicState.agents).find(agent => agent.agent_id !== '广陵王');

        const queue = [[player.location_id]];
        const visited = new Set([player.location_id]);
        let route = [];
        while (queue.length) {
            const path = queue.shift();
            if (path[path.length - 1] === target.location_id) {
                route = path;
                break;
            }
            for (const next of publicState.locations[path[path.length - 1]].connections || []) {
                if (!visited.has(next)) {
                    visited.add(next);
                    queue.push([...path, next]);
                }
            }
        }
        for (const destination of route.slice(1)) {
            await live.locator(`[data-location-id="${destination}"].reachable-room`).click();
            await live.locator('#map-move-confirm:not(.hidden)').waitFor();
            await live.locator('#confirm-map-move').click();
            await live.locator(`[data-location-id="${destination}"].current-room`).waitFor({timeout: 30000});
        }

        await live.locator(`.agent-token[data-agent-id="${target.agent_id}"].talkable-agent`).click();
        await live.locator('#conversation-composer:not(.hidden)').waitFor();
        await live.locator('#conversation-memory').selectOption({index: 1});
        await live.locator('#conversation-content').fill('这条线索与你记得的时辰一致吗？');
        await live.locator('#send-conversation').click();
        await live.waitForFunction(() => document.querySelectorAll('#conversation-thread .dialogue-entry').length >= 2, null, {timeout: 120000});
        const firstThread = await live.locator('#conversation-thread').textContent();

        await live.locator('#conversation-content').fill('你愿意拿什么亲历来证明这句话？');
        await live.locator('#send-conversation').click();
        await live.waitForFunction(() => document.querySelectorAll('#conversation-thread .dialogue-entry').length >= 4, null, {timeout: 120000});
        const secondThread = await live.locator('#conversation-thread').textContent();

        const nextRoom = await live.locator('.reachable-room').first().getAttribute('data-location-id');
        await live.locator(`[data-location-id="${nextRoom}"].reachable-room`).click();
        await live.locator('#confirm-map-move').click();
        await live.locator(`[data-location-id="${nextRoom}"].current-room`).waitFor({timeout: 30000});
        const movePopupHidden = await live.locator('#player-event-feedback').evaluate(
            element => element.classList.contains('hidden')
        );

        await live.locator('#end-player-round').click();
        await live.locator('#continue-next-round:not(.hidden)').waitFor({timeout: 240000});
        const discussionTabs = await live.locator('#conversation-tabs button').count();
        const discussionLabel = await live.locator('#conversation-tabs').textContent();
        const lobbyComposerEnabled = await live.locator('#send-conversation').isEnabled();
        await live.locator('#continue-next-round').click();
        await live.waitForFunction(() => (
            document.querySelector('#live-round')?.textContent === '2'
            && document.querySelector('#live-round-timer-state')?.textContent === '本轮探索'
        ), null, {timeout: 30000});

        const result = {
            target: target.display_name,
            timer: await live.locator('#live-round-timer-value').textContent(),
            firstThread,
            secondThread,
            movePopupHidden,
            genericMoveButtons: await live.locator('[data-intent-type="move"]').count(),
            genericTalkButtons: await live.locator('[data-intent-type="talk"]').count(),
            discussionTabs,
            discussionLabel,
            lobbyComposerEnabled,
            continuedRound: await live.locator('#live-round').textContent(),
            errors,
        };
        if (
            !firstThread.includes('交换情报')
            || secondThread === firstThread
            || !result.movePopupHidden
            || result.genericMoveButtons
            || result.genericTalkButtons
            || result.discussionTabs !== 1
            || !result.discussionLabel.includes('大堂讨论')
            || !result.lobbyComposerEnabled
            || result.continuedRound !== '2'
            || errors.length
        ) {
            throw new Error(`Unexpected conversation UI: ${JSON.stringify(result)}`);
        }
        process.stdout.write(`${JSON.stringify(result)}\n`);
    } finally {
        await browser.close();
    }
})().catch(error => {
    process.stderr.write(`${error.stack || error}\n`);
    process.exit(1);
});
