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

        const director = await context.newPage();
        watch(director);
        await director.goto(`${baseUrl}/interactive/director`, {waitUntil: 'networkidle'});
        await director.locator('#game:not(.hidden)').waitFor();
        await director.locator('.event-card').first().click();
        await live.waitForFunction(() => !document.querySelector('[data-intent-type="move"]')?.disabled);

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
            await live.locator('[data-intent-type="move"]').click();
            await live.locator('#action-destination').selectOption(destination);
            await live.locator('#submit-action').click();
            await live.locator('#player-event-feedback.shown').waitFor({timeout: 30000});
            await live.locator('#player-event-close').click();
            await live.locator('#player-event-feedback').waitFor({state: 'hidden'});
        }

        await live.locator('[data-intent-type="talk"]').click();
        await live.locator('#action-target').selectOption(target.agent_id);
        await live.locator('#action-memory').selectOption({index: 1});
        const explicitExchangeText = await live.locator('#action-content').inputValue();
        await live.locator('#submit-action').click();
        await live.locator('#player-event-feedback.shown').waitFor({timeout: 120000});
        const firstKicker = await live.locator('#player-event-kicker').textContent();
        const firstReply = await live.locator('#player-event-summary').textContent();
        await live.locator('#player-event-close').click();
        await live.locator('#player-event-feedback').waitFor({state: 'hidden'});

        const talkStillSelected = await live.locator('[data-intent-type="talk"]').evaluate(
            element => element.classList.contains('selected')
        );
        const secondSubmitEnabled = await live.locator('#submit-action').isEnabled();
        await live.locator('#action-content').fill('你愿意拿什么线索证明这句话？');
        await live.locator('#submit-action').click();
        await live.locator('#player-event-feedback.shown').waitFor({timeout: 120000});
        const secondKicker = await live.locator('#player-event-kicker').textContent();
        const secondReply = await live.locator('#player-event-summary').textContent();
        await live.locator('#player-event-close').click();
        await live.locator('#player-event-feedback').waitFor({state: 'hidden'});

        await live.locator('[data-intent-type="move"]').click();
        await live.locator('#submit-action').click();
        await live.locator('#player-event-feedback.shown').waitFor({timeout: 30000});
        await live.locator('#player-event-close').click();
        await live.locator('#player-event-feedback').waitFor({state: 'hidden'});
        const moveStillSelected = await live.locator('[data-intent-type="move"]').evaluate(
            element => element.classList.contains('selected')
        );
        const consecutiveMoveEnabled = await live.locator('#submit-action').isEnabled();
        const archivedExchange = await live.locator('#conversation-thread').textContent();

        const result = {
            target: target.display_name,
            firstKicker,
            firstReply,
            secondKicker,
            secondReply,
            talkStillSelected,
            secondSubmitEnabled,
            moveStillSelected,
            consecutiveMoveEnabled,
            explicitExchangeText,
            archivedExchange,
            errors,
        };
        if (
            !firstKicker.includes('回应了你')
            || !secondKicker.includes('回应了你')
            || !firstReply
            || !secondReply
            || !talkStillSelected
            || !secondSubmitEnabled
            || !moveStillSelected
            || !consecutiveMoveEnabled
            || !explicitExchangeText.includes('我愿意把这条情报告诉你')
            || !archivedExchange.includes('交换情报')
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
