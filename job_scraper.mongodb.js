/* global use, db */
// MongoDB Playground for Job_Scraper
// Use this template to inspect and query job scraping data in VS Code.

// 1. Select the database to use.
use('Job_Scraper');

// 2. Clear any existing sample data (optional, uncomment to reset)
// db.getCollection('JOBS').drop();

// 3. Insert sample verified job listings to demonstrate the schema
// Note: In our scraper, when a duplicate job is found, the 'site' field gets updated 
// to include both sources separated by a comma (e.g., 'Glassdoor, LinkedIn').
db.getCollection('JOBS').insertMany([
  {
    "title": "Junior QA Engineer",
    "company": "ITWorks InfoTech Private Limited",
    "location": "Pune, India",
    "about_job": "QA Test Engineer (Manual) with 1–3 years of experience. Strong STLC and Jira skills required.",
    "site": "Glassdoor, LinkedIn",
    "url": "https://www.glassdoor.co.in/job-listing/junior-qa-engineer...",
    "salary": "INR 300000 - 400000",
    "experience_required": "1-3 years",
    "scraped_at": new Date().toISOString(),
    "job_id": "1010181278231"
  },
  {
    "title": "QA Automation Engineer",
    "company": "TransPerfect",
    "location": "Pune, India",
    "about_job": "Looking for QA Automation Engineers with Python and Selenium experience. Mid level.",
    "site": "Glassdoor",
    "url": "https://www.glassdoor.co.in/job-listing/qa-automation-engineer...",
    "salary": null,
    "experience_required": "1-3 years",
    "scraped_at": new Date().toISOString(),
    "job_id": "1010108137361"
  },
  {
    "title": "QA Engineer",
    "company": "Checkmarx",
    "location": "Pune, India",
    "about_job": "Checkmarx is seeking a QA Engineer for application security testing. Manual + automation skills.",
    "site": "LinkedIn",
    "url": "https://in.linkedin.com/jobs/view/qa-engineer-at-checkmarx...",
    "salary": null,
    "experience_required": "1-3 years",
    "scraped_at": new Date().toISOString(),
    "job_id": "4280833100"
  },
  {
    "title": "Senior QA Tester",
    "company": "Endava",
    "location": "Pune, India",
    "about_job": "Senior QA position. Automation using Java/Selenium. Minimum 5 years of experience.",
    "site": "LinkedIn, Indeed",
    "url": "https://in.linkedin.com/jobs/view/senior-qa-tester-at-endava...",
    "salary": "INR 1200000",
    "experience_required": "3-5 years",
    "scraped_at": new Date().toISOString(),
    "job_id": "4405857418"
  }
]);

// 4. Retrieve all scraped jobs in the JOBS collection
console.log("=== All Scraped Jobs ===");
const allJobs = db.getCollection('JOBS').find({}).toArray();
printjson(allJobs);

// 5. Query for cross-posted jobs (listings found on more than one site)
console.log("\n=== Cross-Posted Jobs (Listed on Multiple Sites) ===");
const crossPostedJobs = db.getCollection('JOBS').find({
  "site": { $regex: "," } // Matches site values containing a comma
}).toArray();
printjson(crossPostedJobs);

// 6. Aggregate analytics: Count jobs per source site
console.log("\n=== Jobs Count by Platform ===");
db.getCollection('JOBS').aggregate([
  // Project to split comma-separated sites into an array
  {
    $project: {
      sites: { $split: ["$site", ", "] }
    }
  },
  // Unwind the array to count each site source individually
  { $unwind: "$sites" },
  // Group by site name and count
  {
    $group: {
      _id: "$sites",
      jobCount: { $sum: 1 }
    }
  },
  { $sort: { jobCount: -1 } }
]);

// 7. Aggregate analytics: Count jobs per company
console.log("\n=== Job Openings by Company ===");
db.getCollection('JOBS').aggregate([
  {
    $group: {
      _id: "$company",
      totalJobs: { $sum: 1 }
    }
  },
  { $sort: { totalJobs: -1 } }
]);
