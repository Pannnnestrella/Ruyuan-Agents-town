const { chromium } = require('playwright');

(async () => {
    const baseUrl = process.env.INTERACTIVE_BASE_URL || 'http://127.0.0.1:5001';
    const screenshotPath = process.env.INTERACTIVE_CROSS_ROUND_SCREENSHOT || '';
    const executablePath = process.env.INTERACTIVE_BROWSER_EXECUTABLE || undefined;
    const browser = await chromium.launch({
        headless: true,
        executablePath,
        args: ['--no-sandbox', '--disable-gpu'],
        timeout: 15000,
    });
    const context = await browser.newContext({viewport: {width: 1560, height: 1050}});
    const errors = [];
    const tasks = [];
    const watch = page => {
        page.on('pageerror', error => errors.push(`pageerror: ${error.message}`));
        page.on('console', message => {
            if (message.type() === 'error') errors.push(`console: ${message.text()}`);
        });
        page.on('response', response => {
            if (response.status() >= 400) errors.push(`response: ${response.status()} ${response.url()}`);
            if (response.status() === 200 && response.url().includes('/api/interactive/tasks/')) {
                response.json().then(task => {
                    if (task.status === 'succeeded' && !tasks.some(item => item.task_id === task.task_id)) {
                        tasks.push(task);
                    }
                }).catch(() => {});
            }
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

        for (let round = 1; round <= 2; round += 1) {
            await director.locator('.event-card').first().click();
            await director.locator('#director-dispatch-layer .world-card.shown').waitFor();
            await director.getByRole('button', {name: '开始整轮（3 次行动）'}).click();
            await director.waitForFunction(
                expected => document.querySelector('#round-number')?.textContent === String(expected),
                round,
                {timeout: 150000},
            );
            await live.waitForFunction(
                expected => document.querySelector('#live-round')?.textContent === String(expected),
                round,
                {timeout: 150000},
            );
        }
        await director.waitForFunction(
            () => document.querySelector('#host-round-title')?.textContent.includes('第 3 轮'),
            null,
            {timeout: 150000},
        );
        if (screenshotPath) await live.screenshot({path: screenshotPath, fullPage: true});
        const result = {
            gameId: await live.evaluate(() => window.localStorage.getItem('interactiveGameId')),
            round: await live.locator('#live-round').textContent(),
            planner: await live.locator('#live-planner').textContent(),
            taskCount: tasks.length,
            completedAgents: tasks.map(task => task.progress?.completed),
            publicActions: await live.locator('.track-events li').count(),
        };
        if (result.round !== '2' || result.taskCount !== 2 || result.publicActions < 6 || errors.length) {
            throw new Error(`Unexpected cross-round UI: ${JSON.stringify(result)}\n${errors.join('\n')}`);
        }
        process.stdout.write(`${JSON.stringify(result)}\n`);
    } finally {
        await browser.close();
    }
})().catch(error => {
    process.stderr.write(`${error.stack || error}\n`);
    process.exit(1);
});
