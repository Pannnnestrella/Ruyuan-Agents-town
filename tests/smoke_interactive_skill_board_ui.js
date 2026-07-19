const { chromium } = require('playwright');

(async () => {
    const baseUrl = process.env.INTERACTIVE_BASE_URL || 'http://127.0.0.1:5001';
    const browser = await chromium.launch({
        headless: true,
        executablePath: process.env.INTERACTIVE_BROWSER_EXECUTABLE || undefined,
        args: ['--no-sandbox', '--disable-gpu'], timeout: 15000,
    });
    const context = await browser.newContext({viewport: {width: 1500, height: 1100}});
    const errors = [];
    try {
        const live = await context.newPage();
        live.on('pageerror', error => errors.push(error.message));
        live.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
        await live.goto(`${baseUrl}/interactive?speed=fast`, {waitUntil: 'networkidle'});
        await live.evaluate(() => localStorage.clear());
        await live.reload({waitUntil: 'networkidle'});
        await live.locator('[data-role-id="左慈"]').click();
        await live.locator('#enter-from-dispatch').click();
        await live.locator('#story-overlay:not(.hidden)').waitFor();
        const roleAbility = await live.locator('#player-abilities').textContent();
        await live.locator('#story-overlay').click({position: {x: 5, y: 5}});
        await live.locator('#story-overlay').waitFor({state: 'hidden'});

        const director = await context.newPage();
        await director.goto(`${baseUrl}/interactive/director`, {waitUntil: 'networkidle'});
        await director.locator('#game:not(.hidden)').waitFor();
        await director.locator('.event-card').first().click();
        await live.waitForFunction(() => !document.querySelector('[data-intent-type="investigate"]')?.disabled);

        const basicSearch = live.locator('[data-intent-type="investigate"]:not([data-ability-id])');
        const toxinSkill = live.locator('[data-ability-id="toxin_diagnosis"]');
        const hasBasicSearch = await basicSearch.count() === 1;
        const hasToxinSkill = await toxinSkill.count() === 1;

        const gameId = (await live.locator('#live-game-id').textContent()).replace('局号 ', '').trim();
        const publicState = await live.evaluate(async ({baseUrl, gameId}) =>
            (await (await fetch(`${baseUrl}/api/interactive/games/${gameId}`)).json()).state,
        {baseUrl, gameId});
        const start = publicState.agents['左慈'].location_id;
        const queue = [[start]];
        const visited = new Set([start]);
        let route = [];
        while (queue.length) {
            const path = queue.shift();
            if (path.at(-1) === 'lobby') { route = path; break; }
            for (const next of publicState.locations[path.at(-1)].connections || []) {
                if (!visited.has(next)) { visited.add(next); queue.push([...path, next]); }
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
        await live.locator('#player-bulletin-composer:not(.hidden)').waitFor();
        const post = '左慈验得茶盏余毒遇雨水会泛青，请诸位勿再触碰。';
        await live.locator('#player-bulletin-content').fill(post);
        await live.locator('#post-player-bulletin').click();
        await live.waitForFunction(text => document.querySelector('#bulletin-posts')?.textContent.includes(text), post);
        const bulletinText = await live.locator('#bulletin-posts').textContent();

        await toxinSkill.click();
        const skillExplanation = await live.locator('#decision-hint').textContent();
        await live.locator('#submit-action').click();
        await live.locator('#action-progress:not(.hidden)').waitFor({timeout: 30000});
        const progressVisible = await live.locator('#action-progress-count').textContent();
        await live.locator('#player-event-feedback.shown').waitFor({timeout: 180000});
        const feedbackPersists = await live.locator('#player-event-feedback.shown').isVisible();
        await live.waitForTimeout(1500);
        const feedbackStillVisible = await live.locator('#player-event-feedback.shown').isVisible();
        await live.locator('#player-event-close').click();

        const result = {roleAbility, hasBasicSearch, hasToxinSkill, bulletinText, skillExplanation, progressVisible, feedbackPersists, feedbackStillVisible, errors};
        if (!roleAbility.includes('辨毒验伤') || !hasBasicSearch || !hasToxinSkill
            || !bulletinText.includes(post) || !skillExplanation.includes('毒物')
            || !feedbackPersists || !feedbackStillVisible || errors.length) {
            throw new Error(`Unexpected skill/board UI: ${JSON.stringify(result)}`);
        }
        process.stdout.write(`${JSON.stringify(result)}\n`);
    } finally {
        await browser.close();
    }
})().catch(error => { process.stderr.write(`${error.stack || error}\n`); process.exit(1); });
