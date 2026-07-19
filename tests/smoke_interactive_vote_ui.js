const { chromium } = require('playwright');

(async () => {
    const baseUrl = process.env.INTERACTIVE_BASE_URL || 'http://127.0.0.1:5001';
    const screenshotPath = process.env.INTERACTIVE_VOTE_SCREENSHOT || '';
    const executablePath = process.env.INTERACTIVE_BROWSER_EXECUTABLE || undefined;
    const browser = await chromium.launch({
        headless: true,
        executablePath,
        args: ['--no-sandbox', '--disable-gpu'],
        timeout: 15000,
    });
    const context = await browser.newContext({viewport: {width: 1600, height: 1100}});
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(`pageerror: ${error.message}`));
    page.on('console', message => {
        if (message.type() === 'error') errors.push(`console: ${message.text()}`);
    });
    page.on('requestfailed', request => errors.push(`requestfailed: ${request.url()}`));
    page.on('response', response => {
        if (response.status() >= 400) errors.push(`response: ${response.status()} ${response.url()}`);
    });

    try {
        await page.goto(`${baseUrl}/interactive?speed=fast`, {waitUntil: 'networkidle'});
        await page.locator('#live-create').click();
        await page.locator('#live-app:not(.hidden)').waitFor();
        const gameId = await page.evaluate(() => window.localStorage.getItem('interactiveGameId'));

        for (let round = 1; round <= 6; round += 1) {
            const stateResponse = await context.request.get(`${baseUrl}/api/interactive/games/${gameId}`);
            const stateData = await stateResponse.json();
            if (stateData.intel?.length) {
                await context.request.post(`${baseUrl}/api/interactive/games/${gameId}/public-intel`, {
                    data: {intel_id: stateData.intel[0].id},
                });
            }
            await context.request.post(`${baseUrl}/api/interactive/games/${gameId}/event-card`, {
                data: {card_id: stateData.empty_event.card_id},
            });
            const queued = await context.request.post(`${baseUrl}/api/interactive/games/${gameId}/rounds/advance`, {data: {}});
            const taskId = (await queued.json()).task_id;
            for (let attempt = 0; attempt < 100; attempt += 1) {
                const task = await (await context.request.get(`${baseUrl}/api/interactive/tasks/${taskId}`)).json();
                if (task.status === 'failed') throw new Error(task.error);
                if (task.status === 'succeeded') break;
                await new Promise(resolve => setTimeout(resolve, 20));
            }
        }

        await page.waitForFunction(() => document.querySelector('#live-round')?.textContent === '6');
        await page.locator('#vote-panel:not(.hidden)').waitFor({timeout: 20000});
        await page.waitForFunction(() => document.querySelectorAll('.vote-card').length === 6);
        if (screenshotPath) await page.screenshot({path: screenshotPath, fullPage: true});
        const result = await page.evaluate(() => ({
            round: document.querySelector('#live-round')?.textContent,
            votes: document.querySelectorAll('.vote-card').length,
            reveal: document.querySelector('.vote-summary h3')?.textContent,
            feed: document.querySelectorAll('.feed-item').length,
        }));
        if (result.round !== '6' || result.votes !== 6 || !result.reveal?.includes('真实凶手')) {
            throw new Error(`Unexpected voting UI: ${JSON.stringify(result)}`);
        }
        if (errors.length) throw new Error(`Browser errors:\n${errors.join('\n')}`);
        process.stdout.write(`${JSON.stringify(result)}\n`);
    } finally {
        await browser.close();
    }
})().catch(error => {
    process.stderr.write(`${error.stack || error}\n`);
    process.exit(1);
});
