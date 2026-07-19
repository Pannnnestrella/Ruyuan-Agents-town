const { chromium } = require('playwright');

(async () => {
    const baseUrl = process.env.INTERACTIVE_BASE_URL || 'http://127.0.0.1:5001';
    const screenshotPath = process.env.INTERACTIVE_PLAYER_SCREENSHOT || '';
    const openingScreenshotPath = process.env.INTERACTIVE_OPENING_SCREENSHOT || '';
    const storyScreenshotPath = process.env.INTERACTIVE_STORY_SCREENSHOT || '';
    const feedbackScreenshotPath = process.env.INTERACTIVE_FEEDBACK_SCREENSHOT || '';
    const executablePath = process.env.INTERACTIVE_BROWSER_EXECUTABLE || undefined;
    const browser = await chromium.launch({
        headless: true,
        executablePath,
        args: ['--no-sandbox', '--disable-gpu'],
        timeout: 15000,
    });
    const context = await browser.newContext({viewport: {width: 1600, height: 1200}});
    const errors = [];
    const succeededTasks = [];
    let privateLeak = false;
    const watch = page => {
        page.on('pageerror', error => errors.push(`pageerror: ${error.message}`));
        page.on('console', message => {
            if (message.type() === 'error') errors.push(`console: ${message.text()}`);
        });
        page.on('response', async response => {
            if (response.status() >= 400) errors.push(`response: ${response.status()} ${response.url()}`);
            if (response.url().includes('/player') && response.request().method() === 'GET') {
                const text = await response.text().catch(() => '');
                if (text.includes('"killer_id"') || text.includes('"killer_profile"')) privateLeak = true;
            }
            if (response.status() === 200 && response.url().includes('/api/interactive/tasks/')) {
                const task = await response.json().catch(() => null);
                if (task?.status === 'succeeded' && !succeededTasks.some(item => item.task_id === task.task_id)) {
                    succeededTasks.push(task);
                }
            }
        });
    };
    try {
        const live = await context.newPage();
        watch(live);
        await live.goto(`${baseUrl}/interactive?speed=fast`, {waitUntil: 'networkidle'});
        await live.evaluate(() => localStorage.clear());
        await live.reload({waitUntil: 'networkidle'});
        await live.locator('.role-option').first().waitFor();
        const roleCount = await live.locator('.role-option').count();
        await live.locator('[data-role-id="广陵王"]').click();
        await live.locator('#opening-overlay:not(.hidden)').waitFor({timeout: 30000});
        const openingText = await live.locator('#opening-body').textContent();
        if (openingScreenshotPath) await live.screenshot({path: openingScreenshotPath, fullPage: true});
        await live.locator('#enter-from-dispatch').click();
        await live.locator('#player-action-column:not(.hidden)').waitFor({timeout: 30000});
        await live.locator('#story-overlay:not(.hidden)').waitFor({timeout: 30000});
        const storyParagraphs = await live.locator('#story-body p').count();
        if (storyScreenshotPath) await live.screenshot({path: storyScreenshotPath, fullPage: true});
        await live.locator('#player-goals .inspectable-tag').first().click();
        await live.locator('#detail-overlay.shown').waitFor();
        const detailTitle = await live.locator('#detail-title').textContent();
        await live.locator('#detail-close').click();
        await live.locator('#detail-overlay').waitFor({state: 'hidden'});
        await live.locator('#story-overlay').click({position: {x: 5, y: 5}});
        await live.locator('#story-overlay').waitFor({state: 'hidden'});
        await live.locator('#dossier-edge-tabs:not(.hidden)').waitFor();
        const layout = await live.evaluate(() => {
            const map = document.querySelector('.map-panel').getBoundingClientRect();
            const action = document.querySelector('#player-action-column').getBoundingClientRect();
            return {mapLeft: map.left, mapTop: map.top, actionLeft: action.left, actionTop: action.top};
        });
        const initialVisibleTokens = await live.locator('.agent-token').count();

        const director = await context.newPage();
        watch(director);
        await director.goto(`${baseUrl}/interactive/director`, {waitUntil: 'networkidle'});
        await director.locator('#game:not(.hidden)').waitFor();
        const directorAdvanceDisabled = await director.locator('#advance-round').isDisabled();
        await director.locator('.event-card').first().click();
        await live.waitForFunction(
            () => [...document.querySelectorAll('[data-intent-type]')].some(button => !button.disabled),
            null,
            {timeout: 30000},
        );

        await live.locator('[data-intent-type="move"]').click();
        await live.locator('#submit-action').click();
        await live.locator('#player-event-feedback.shown').waitFor({timeout: 30000});
        const freeActionFeedback = await live.locator('#player-event-kicker').textContent();
        const freeActionStep = await live.locator('#live-action-step').textContent();
        if (feedbackScreenshotPath) await live.screenshot({path: feedbackScreenshotPath, fullPage: true});
        await live.locator('#player-event-close').click();
        await live.locator('#player-event-feedback').waitFor({state: 'hidden'});

        for (let step = 1; step <= 3; step += 1) {
            const investigate = live.locator('[data-intent-type="investigate"]');
            if (await investigate.isEnabled()) {
                await investigate.click();
            } else {
                await live.locator('[data-intent-type]:not(.free-action):not([disabled])').first().click();
            }
            await live.locator('#submit-action').click();
            await live.waitForFunction(
                ({expectedStep}) => {
                    const round = Number(document.querySelector('#live-round')?.textContent || 0);
                    const stepText = document.querySelector('#live-action-step')?.textContent || '';
                    return expectedStep < 3
                        ? stepText.includes(`行动 ${expectedStep}/3`)
                        : round === 1 && stepText.includes('行动 0/3');
                },
                {expectedStep: step},
                {timeout: 180000},
            );
        }

        await director.waitForFunction(
            () => [...document.querySelectorAll('#event-cards [data-card-id]')].some(button => !button.disabled),
            null,
            {timeout: 30000},
        );
        const directorNextCardEnabled = await director.locator('#event-cards [data-card-id]').first().isEnabled();
        await live.locator('#auto-host-next-round:not(.hidden)').waitFor({timeout: 30000});
        await live.locator('#auto-host-next-round').click();
        await live.waitForFunction(
            () => [...document.querySelectorAll('[data-intent-type]')].some(button => !button.disabled),
            null,
            {timeout: 30000},
        );

        if (screenshotPath) await live.screenshot({path: screenshotPath, fullPage: true});
        const result = {
            roleCount,
            playerName: await live.locator('#player-name').textContent(),
            round: await live.locator('#live-round').textContent(),
            actionStep: await live.locator('#live-action-step').textContent(),
            memories: await live.locator('#player-memories .inspectable-tag').count(),
            privateCards: await live.locator('#player-secrets .inspectable-tag').count(),
            storyParagraphs,
            openingHasFakeReport: openingText.includes('不得复核来路'),
            detailTitle,
            guideTitle: await live.locator('#story-guide-title').textContent(),
            mapBeforeAction: layout.mapLeft < layout.actionLeft && Math.abs(layout.mapTop - layout.actionTop) < 6,
            initialVisibleTokens,
            freeActionFeedback,
            freeActionStep,
            taskCount: succeededTasks.length,
            directorAdvanceDisabled,
            directorNextCardEnabled,
            privateLeak,
        };
        if (
            result.roleCount !== 6
            || result.playerName !== '广陵王'
            || result.round !== '1'
            || result.taskCount !== 4
            || result.memories < 4
            || result.storyParagraphs !== 3
            || !result.openingHasFakeReport
            || !result.detailTitle.includes('任务')
            || !result.mapBeforeAction
            || result.initialVisibleTokens !== 1
            || !result.freeActionFeedback.includes('自由探索')
            || !result.freeActionStep.includes('主要行动 0/3')
            || !result.directorAdvanceDisabled
            || !result.directorNextCardEnabled
            || result.privateLeak
            || errors.length
        ) {
            throw new Error(`Unexpected player UI: ${JSON.stringify(result)}\n${errors.join('\n')}`);
        }
        process.stdout.write(`${JSON.stringify(result)}\n`);
    } finally {
        await browser.close();
    }
})().catch(error => {
    process.stderr.write(`${error.stack || error}\n`);
    process.exit(1);
});
