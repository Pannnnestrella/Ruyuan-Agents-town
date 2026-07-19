const { chromium } = require('playwright');

(async () => {
    const baseUrl = process.env.INTERACTIVE_BASE_URL || 'http://127.0.0.1:5001';
    const screenshotPath = process.env.INTERACTIVE_LIVE_SCREENSHOT || '';
    const executablePath = process.env.INTERACTIVE_BROWSER_EXECUTABLE || undefined;
    const browser = await chromium.launch({
        headless: true,
        executablePath,
        args: ['--no-sandbox', '--disable-gpu'],
        timeout: 15000,
    });
    const context = await browser.newContext({viewport: {width: 1600, height: 1100}});
    const browserErrors = [];
    const watchPage = page => {
        page.on('pageerror', error => browserErrors.push(`pageerror: ${error.message}`));
        page.on('console', message => {
            if (message.type() === 'error') browserErrors.push(`console: ${message.text()}`);
        });
        page.on('requestfailed', request => {
            browserErrors.push(`requestfailed: ${request.method()} ${request.url()} (${request.failure()?.errorText || 'unknown'})`);
        });
        page.on('response', response => {
            if (response.status() >= 400) browserErrors.push(`response: ${response.status()} ${response.url()}`);
        });
    };

    const livePage = await context.newPage();
    watchPage(livePage);
    try {
        await livePage.goto(`${baseUrl}/interactive?speed=fast`, {waitUntil: 'networkidle'});
        const directorPage = await context.newPage();
        watchPage(directorPage);
        await directorPage.goto(`${baseUrl}/interactive/director`, {waitUntil: 'networkidle'});
        await livePage.locator('#live-create').click();
        await livePage.locator('#live-app:not(.hidden)').waitFor();
        await livePage.locator('.agent-token').first().waitFor();
        await directorPage.locator('#game:not(.hidden)').waitFor();
        for (let round = 1; round <= 4; round += 1) {
            await directorPage.locator('.intel-option').first().click();
            if (round === 1) await livePage.locator('#live-dispatch-layer .yuan-report.shown').waitFor();
            await directorPage.locator('.event-card').first().click();
            if (round === 1) await livePage.locator('#live-dispatch-layer .world-card.shown').waitFor();
        await directorPage.getByRole('button', {name: '开始整轮（3 次行动）'}).click();
            await directorPage.waitForFunction(expected => document.querySelector('#round-number')?.textContent === String(expected), round);
            await livePage.waitForFunction(expected => document.querySelector('#live-round')?.textContent === String(expected), round);
            await livePage.waitForTimeout(350);
        }
        await livePage.waitForFunction(() => [...document.querySelectorAll('.feed-item strong')].some(item => item.textContent.includes('前往')));
        await livePage.waitForFunction(() => [...document.querySelectorAll('.feed-item strong')].some(item => item.textContent.includes('说：“')));
        await livePage.waitForFunction(() => document.querySelectorAll('.track-events li').length >= 6);
        if (screenshotPath) await livePage.screenshot({path: screenshotPath, fullPage: true});

        const result = await livePage.evaluate(() => ({
            round: document.querySelector('#live-round')?.textContent,
            rooms: document.querySelectorAll('.live-room').length,
            tokens: document.querySelectorAll('.agent-token').length,
            tracks: document.querySelectorAll('.track-card').length,
            feed: document.querySelectorAll('.feed-item').length,
            moves: [...document.querySelectorAll('.feed-item strong')].filter(item => item.textContent.includes('前往')).length,
            conversations: [...document.querySelectorAll('.feed-item strong')].filter(item => item.textContent.includes('说：“')).length,
        }));
        if (result.round !== '4' || result.rooms !== 12 || result.tokens !== 6 || result.tracks !== 6 || result.moves < 1 || result.conversations < 1) {
            throw new Error(`Unexpected live UI state: ${JSON.stringify(result)}`);
        }
        if (browserErrors.length) throw new Error(`Browser errors:\n${browserErrors.join('\n')}`);
        process.stdout.write(`${JSON.stringify(result)}\n`);
    } finally {
        await browser.close();
    }
})().catch(error => {
    process.stderr.write(`${error.stack || error}\n`);
    process.exit(1);
});
