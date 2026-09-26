import dotenv from 'dotenv';
import path from 'path';

dotenv.config({ path: path.resolve(__dirname, '..', '.env') });
dotenv.config({ path: path.resolve(__dirname, '..', '..', '.env') });

export const credentials = {
  email: process.env.LINKEDIN_EMAIL ?? process.env.USER_EMAIL ?? '',
  password: process.env.LINKEDIN_PASSWORD ?? process.env.USER_PASSWORD ?? '',
};
