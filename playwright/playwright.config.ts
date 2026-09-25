import { defineConfig, devices } from '@playwright/test';
import dotenv from 'dotenv';
import path from 'path';

/**
 * Read environment variables from file.
 * https://github.com/motdotla/dotenv
 */
dotenv.config({ path: path.resolve(__dirname, '.env') });
dotenv.config({ path: path.resolve(__dirname, '..', '.env') });

/**
 * See https://playwright.dev/docs/test-configuration.
 */
export default defineConfig({
    testDir: './tests',
    /* Run tests in files in parallel */
    fullyParallel: true,
    /* Fail the build on CI if you accidentally left test.only in the source code. */
    forbidOnly: !!process.env.CI,
    /* Retries help absorb transient load-related flakiness */
    retries: 2,
    /* Fixed, moderate worker count rather than auto-detecting from CPU cores */
    workers: process.env.CI ? 1 : 3,
    /* Reporter to use. See https://playwright.dev/docs/test-reporters */
    reporter: 'html',
    /* Shared settings for all the projects below. See https://playwright.dev/docs/api/class-testoptions. */
    use: {
        /* Base URL to use in actions like `await page.goto('')`. */
        baseURL: process.env.BASE_URL ?? 'https://www.linkedin.com/',

        /* Collect trace, screenshot, and video for failed tests. See https://playwright.dev/docs/trace-viewer */
        trace: 'retain-on-failure',
        screenshot: 'only-on-failure',
        video: 'retain-on-failure',

        /* Maximize the browser window in headed runs */
        viewport: null,
        launchOptions: { args: ['--start-maximized'] },

        /* Reduce motion for UI consistency */
        contextOptions: {
            reducedMotion: 'reduce',
        },
    },

    /* Configure projects for major browsers */
    projects: [
        {
            name: 'setup',
            testMatch: /auth\.setup\.ts/,
        },

        {
            name: 'MartinRyan',
            use: { ...devices['Desktop Chrome'], storageState: 'playwright/.auth/user.json' },
            dependencies: ['setup'],
        },
    ],
});