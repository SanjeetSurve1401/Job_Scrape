import { Page, Locator } from '@playwright/test';

export class LoginPage {
    readonly page: Page;

    readonly loginNavigation: {
        // readonly signInBtn: Locator;
        readonly emailInput: Locator;
        readonly passwordInput: Locator;
        readonly submitBtn: Locator;
    }

    constructor(page: Page) {
        this.page = page;

        this.loginNavigation = {
            // signInBtn: page.getByText('Sign in', { exact: true}),
            emailInput: page.getByRole('textbox', { name: 'Email or Phone' }),
            passwordInput: page.getByLabel('Password'),
            submitBtn: page.locator('//button[.//span[normalize-space()="Sign in"]]'),
        }
    }

    async goto() {
        await this.page.goto('/login');
    }

    async login(email: string, password: string) {
        await this.loginNavigation.emailInput.fill(email);
        await this.loginNavigation.passwordInput.fill(password);
        await this.loginNavigation.submitBtn.click();
    }
}