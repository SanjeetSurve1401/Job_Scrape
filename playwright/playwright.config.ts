import { defineConfig, devices } from '@playwright/test';

import dotenv from 'dotenv';
import path from 'path';
dotenv.config({ path: path.resolve(__dirname, '.env') });

export default defineConfig({
    testDir: './tests',
    fullyParallel: true,
    forbidOnly: !!process.env.CI,
    retries: 2,
    workers: process.env.CI ? 1 : 3,
    reporter: 'html',
    use: {
        baseURL: process.env.BASE_URL ?? 'https://www.linkedin.com/',

        trace: 'retain-on-failure',
        screenshot: 'only-on-failure',
        video: 'retain-on-failure',

        viewport: null,
        launchOptions: { args: ['--start-maximized'] },

        contextOptions: {
            reducedMotion: 'reduce',
        },
    },

    projects: [
        
        {
            name: 'LinkedIn',
            use: { ...devices['Webkit'], storageState: 'playwright/.auth/user.json' },
            dependencies: ['setup'],
        },
    ],
});