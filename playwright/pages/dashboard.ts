import {Page, Locator} from "@playwright/test";

export class DashboardPage {
    readonly page: Page;

    readonly jobsNavigation: {
        readonly jobsBtn: Locator;
    }

    readonly searchNavigation: {
        readonly searchJobs: Locator;
        readonly locationFilter: Locator;
    }

    readonly jobCards: {
        readonly job: Locator;
        readonly nextPageBtn: Locator;
        readonly easyApply: Locator;
    }



    constructor(page: Page) {
        this.page = page;

        this.jobsNavigation = {
            jobsBtn: page.getByText('Jobs', { exact: true }),
        };

        this.searchNavigation = {
            searchJobs: page.getByRole('textbox', {name: /Title, skill or Company/i}),
            locationFilter: page.getByRole('textbox', {name: /City, state, or zip code/i}),
        };

        this.jobCards = {
            job: page.frameLocator('iframe').locator('div.display-flex.job-card-container.relative.job-card-list.job-card-container--clickable.job-card-list--underline-title-on-hover.jobs-search-results-list__list-item--active.jobs-search-two-pane__job-card-container--viewport-tracking-0'),
            nextPageBtn: page.getByRole('button', {name: 'Next'}),
            easyApply: page.locator('//button[normalize-space()="Easy Apply"]'),
            
            // const jobCount = await job.count(),
        }
    } 

    async goto() {
        await this.page.goto('/feed/');
    }


}