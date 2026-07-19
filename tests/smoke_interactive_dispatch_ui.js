const { chromium } = require('playwright');

(async () => {
    const baseUrl = process.env.INTERACTIVE_BASE_URL || 'http://127.0.0.1:5001';
    const directorShot = process.env.INTERACTIVE_DIRECTOR_CARD_SCREENSHOT || '';
    const liveShot = process.env.INTERACTIVE_LIVE_CARD_SCREENSHOT || '';
    const executablePath = process.env.INTERACTIVE_BROWSER_EXECUTABLE || undefined;
    const browser = await chromium.launch({
        headless: true,
        executablePath,
        args: ['--no-sandbox', '--disable-gpu'],
        timeout: 15000,
    });
    const context = await browser.newContext({viewport: {width: 1500, height: 1050}});
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
        const director = await context.newPage();
        watch(live);
        watch(director);
        await live.goto(`${baseUrl}/interactive?speed=fast`, {waitUntil: 'networkidle'});
        await director.goto(`${baseUrl}/interactive/director`, {waitUntil: 'networkidle'});
        await live.locator('#live-create').click();
        await director.locator('#game:not(.hidden)').waitFor();

        await director.locator('.intel-option').first().click();
        await director.locator('#director-dispatch-layer .yuan-report.shown').waitFor();
        await live.locator('#live-dispatch-layer .yuan-report.shown').waitFor();
        if (directorShot) await director.screenshot({path: directorShot, fullPage: true});

        await director.locator('.event-card').first().click();
        await director.locator('#director-dispatch-layer .world-card.shown').waitFor();
        await live.locator('#live-dispatch-layer .world-card.shown').waitFor();
        if (liveShot) await live.screenshot({path: liveShot, fullPage: true});

        const result = {
            hostConsole: await director.locator('.host-console').count(),
            directorReports: await director.locator('.dispatch-card.shown').count(),
            liveReports: await live.locator('.dispatch-card.shown').count(),
            planner: await director.locator('#planner-label').textContent(),
        };
        if (!result.hostConsole || !result.directorReports || !result.liveReports || errors.length) {
            throw new Error(`Unexpected dispatch UI: ${JSON.stringify(result)}\n${errors.join('\n')}`);
        }
        process.stdout.write(`${JSON.stringify(result)}\n`);
    } finally {
        await browser.close();
    }
})().catch(error => {
    process.stderr.write(`${error.stack || error}\n`);
    process.exit(1);
});
