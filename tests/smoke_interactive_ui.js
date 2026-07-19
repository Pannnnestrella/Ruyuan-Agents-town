const { chromium } = require('playwright');

(async () => {
    const baseUrl = process.env.INTERACTIVE_BASE_URL || 'http://127.0.0.1:5001';
    const screenshotPath = process.env.INTERACTIVE_SCREENSHOT || '';
    const executablePath = process.env.INTERACTIVE_BROWSER_EXECUTABLE || undefined;
    const browser = await chromium.launch({
        headless: true,
        executablePath,
        args: ['--no-sandbox', '--disable-gpu'],
        timeout: 15000,
    });
    const page = await browser.newPage({viewport: {width: 1440, height: 1100}});
    const browserErrors = [];
    let resolveCompletedTask;
    const completedTask = new Promise(resolve => { resolveCompletedTask = resolve; });
    page.on('pageerror', error => browserErrors.push(`pageerror: ${error.message}`));
    page.on('console', message => {
        if (message.type() === 'error') browserErrors.push(`console: ${message.text()}`);
    });
    page.on('requestfailed', request => {
        browserErrors.push(`requestfailed: ${request.method()} ${request.url()} (${request.failure()?.errorText || 'unknown'})`);
    });
    page.on('response', response => {
        if (response.status() >= 400) browserErrors.push(`response: ${response.status()} ${response.url()}`);
        if (response.status() === 200 && response.url().includes('/api/interactive/tasks/')) {
            response.json().then(task => {
                if (task.status === 'succeeded') resolveCompletedTask(task);
            }).catch(() => {});
        }
    });
    try {
        await page.goto(`${baseUrl}/interactive/director`, {waitUntil: 'networkidle'});
        await page.getByRole('button', {name: '开始新的六轮推演'}).click();
        await page.locator('#game:not(.hidden)').waitFor();
        await page.getByText('你的主持视角').waitFor();
        await page.locator('#notice-content').fill('所有住客暂留客栈，发现密信后立即登记。');
        await page.getByRole('button', {name: '张贴公告'}).click();
        await page.locator('.notice-pill').waitFor();
        await page.locator('.event-card').first().click();
        await page.locator('#director-dispatch-layer .world-card.shown').waitFor();
        await page.getByRole('button', {name: '开始整轮（3 次行动）'}).click();
        await page.waitForFunction(() => document.querySelector('#round-number')?.textContent === '1');
        const task = await Promise.race([
            completedTask,
            new Promise((_, reject) => setTimeout(() => reject(new Error('Completed task response was not observed')), 5000)),
        ]);
        if (screenshotPath) {
            await page.screenshot({path: screenshotPath, fullPage: true});
        }
        const result = await page.evaluate(() => ({
            title: document.querySelector('#game-title')?.textContent,
            round: document.querySelector('#round-number')?.textContent,
            cards: document.querySelectorAll('.event-card').length,
            notices: document.querySelectorAll('.notice-pill').length,
            agents: document.querySelectorAll('.agent-item').length,
            hostConsole: Boolean(document.querySelector('.host-console')),
        }));
        result.planner = task.result?.state?.planner;
        result.progress = task.progress;
        if (result.round !== '1' || result.cards !== 3 || result.notices !== 1 || result.agents !== 6 || !result.hostConsole) {
            throw new Error(`Unexpected UI state: ${JSON.stringify(result)}`);
        }
        if (browserErrors.length) {
            throw new Error(`Browser errors:\n${browserErrors.join('\n')}`);
        }
        process.stdout.write(`${JSON.stringify(result)}\n`);
    } finally {
        await browser.close();
    }
})().catch(error => {
    process.stderr.write(`${error.stack || error}\n`);
    process.exit(1);
});
