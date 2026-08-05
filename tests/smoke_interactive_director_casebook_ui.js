const { chromium } = require('playwright');

(async () => {
    const baseUrl = process.env.INTERACTIVE_BASE_URL || 'http://127.0.0.1:5001';
    const browser = await chromium.launch({
        headless: true,
        executablePath: process.env.INTERACTIVE_BROWSER_EXECUTABLE || undefined,
        args: ['--no-sandbox', '--disable-gpu'],
        timeout: 15000,
    });
    const page = await browser.newPage({viewport: {width: 1500, height: 1100}});
    const errors = [];
    page.on('pageerror', error => errors.push(`pageerror: ${error.message}`));
    page.on('console', message => {
        if (message.type() === 'error') errors.push(`console: ${message.text()}`);
    });
    try {
        await page.goto(`${baseUrl}/interactive/director`, {waitUntil: 'networkidle'});
        await page.evaluate(() => localStorage.clear());
        await page.reload({waitUntil: 'networkidle'});
        await page.locator('#create-game').click();
        await page.locator('#director-casebook:not(.hidden)').waitFor({timeout: 15000});

        const killerSeal = (await page.locator('#casebook-killer').textContent()).trim();
        const murderSteps = await page.locator('#murder-chain .murder-step').count();
        const characterFiles = await page.locator('#director-character-files details').count();
        const killerFiles = await page.locator('#director-character-files .killer-file').count();
        const clueGroups = await page.locator('#director-clue-map .clue-location-group').count();
        const clueCards = await page.locator('#director-clue-map .clue-card').count();
        const deductionGuides = await page.locator('#variant-deduction-guides .variant-guide').count();
        const activeGuide = page.locator('#variant-deduction-guides .active-variant');
        const activeGuideOpen = await activeGuide.getAttribute('open');
        const activeGuideText = await activeGuide.textContent();
        const killerFile = page.locator('#director-character-files .killer-file');
        await killerFile.locator('summary').click();
        const killerText = await killerFile.textContent();
        const fullTimelineTitle = (await page.locator('.timeline-panel h2').textContent()).trim();
        const objectiveTimelineText = await page.locator('#casebook-objective-timeline').textContent();

        const result = {
            killerSeal,
            murderSteps,
            characterFiles,
            killerFiles,
            clueGroups,
            clueCards,
            deductionGuides,
            activeGuideOpen: activeGuideOpen !== null,
            activeGuideHasConclusion: activeGuideText.includes('理想锁凶结论'),
            hasBackground: killerText.includes('人物背景'),
            hasSecrets: killerText.includes('所有秘密'),
            hasMemories: killerText.includes('完整记忆与情报'),
            hasInventory: killerText.includes('当前持有物'),
            hasActions: killerText.includes('本局行动与发言'),
            hasMidnightTime: objectiveTimelineText.includes('子初(23:00)'),
            hasAfternoonTime: objectiveTimelineText.includes('申正(16:00)'),
            fullTimelineTitle,
            errors,
        };
        console.log(JSON.stringify(result));
        if (
            !killerSeal.includes('本局凶手')
            || murderSteps !== 5
            || characterFiles !== 6
            || killerFiles !== 1
            || clueGroups < 8
            || clueCards < 30
            || deductionGuides !== 3
            || activeGuideOpen === null
            || !result.activeGuideHasConclusion
            || !result.hasBackground
            || !result.hasSecrets
            || !result.hasMemories
            || !result.hasInventory
            || !result.hasActions
            || !result.hasMidnightTime
            || !result.hasAfternoonTime
            || fullTimelineTitle !== '全量推演事件'
            || errors.length
        ) process.exitCode = 1;
    } finally {
        await browser.close();
    }
})().catch(error => {
    console.error(error);
    process.exit(1);
});
