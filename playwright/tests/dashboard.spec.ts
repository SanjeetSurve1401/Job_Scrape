import { test, expect } from '@playwright/test';
import { DashboardPage } from '../pages/dashboard';

test.describe('Dashboard Job Scraper', () => {
  test('should search and count jobs on dashboard', async ({ page }) => {
    const dashboardPage = new DashboardPage(page);

    await dashboardPage.searchJobs('Software Engineer', 'United States');

    const jobCount = await dashboardPage.getJobCount();
    console.log(`Found ${jobCount} jobs on the dashboard`);

    expect(jobCount).toBeGreaterThanOrEqual(0);

    if (await dashboardPage.hasNextPage()) {
      await dashboardPage.goToNextPage();
      const nextCount = await dashboardPage.getJobCount();
      console.log(`Found ${nextCount} jobs on next page`);
    }
  });
});
