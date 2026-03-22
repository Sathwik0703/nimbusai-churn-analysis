<img width="2385" height="744" alt="rfm_segments" src="https://github.com/user-attachments/assets/cbddf498-e07b-4444-9802-738efaede1ca" />
<img width="1782" height="593" alt="hypothesis_test" src="https://github.com/user-attachments/assets/e014181b-718b-433e-97f5-10c495f00f58" />
# nimbusai-churn-analysis
Data Analyst Intern Take-Home Challenge — Churn &amp; Retention Analysis
# NimbusAI — Churn & Retention Analysis
### Data Analyst Intern Take-Home Challenge

---

## Overview
This project analyzes customer churn for NimbusAI, a B2B SaaS company
with 1,200+ customers. The analysis combines PostgreSQL subscription data
with MongoDB user activity logs to identify churn drivers and recommend
retention strategies.

**Focus Area:** Option A — Customer Churn & Retention Analysis

---

## Key Findings

| Finding | Detail |
|---|---|
| Overall churn rate | Calculated across 1,204 customers |
| Top churn signal | 3+ support tickets in 30 days before renewal |
| Engagement impact | Retained customers have significantly higher engagement (p < 0.05) |
| Highest risk segment | At-Risk RFM segment — high LTV, dropping engagement |
| Upsell opportunity | Top 20 free-tier users with high engagement scores |

---

## Repository Structure

```
nimbusai-churn-analysis/
│
├── README.md
├── sql/
│   └── queries.sql          # 5 PostgreSQL queries (joins, window fn, CTEs)
├── mongodb/
│   └── mongo_queries.js     # 4 aggregation pipelines
├── python/
│   ├── churn_analysis.py    # Wrangling, hypothesis test, RFM segmentation
│   ├── import_mongo_fixed.py# MongoDB data importer
│   └── requirements.txt     # Python dependencies
├── outputs/
│   ├── hypothesis_test.png  # Mann-Whitney U test visualization
│   └── rfm_segments.png     # RFM segmentation charts
└── dashboard/
    └── dashboard_link.txt   # Power BI published dashboard link
```

---

## Databases

| Database | Type | Contains |
|---|---|---|
| nimbus_core | PostgreSQL 18 | customers, subscriptions, plans, billing, tickets, team_members, feature_flags |
| nimbus_events | MongoDB | user_activity_logs, onboarding_events, nps_survey_responses |

---

## Task 1 — SQL Queries

File: `sql/queries.sql`

| Query | Technique | Description |
|---|---|---|
| Q1 | Joins + Aggregation | Active customers, avg MRR, ticket rate per plan |
| Q2 | Window Functions | Customer LTV ranking within plan tier |
| Q3 | CTEs + Subqueries | Customers who downgraded after high ticket volume |
| Q4 | Time Series | MoM subscription growth + rolling 3-month churn rate |
| Q5 | Advanced | Duplicate customer detection using pg_trgm similarity |

---

## Task 2 — MongoDB Queries

File: `mongodb/mongo_queries.js`

| Query | Description |
|---|---|
| Q1 | Avg sessions per user per week + duration percentiles |
| Q2 | DAU and 7-day retention rate per event type |
| Q3 | Onboarding funnel drop-off rates and time between steps |
| Q4 | Top 20 free-tier upsell targets by engagement score |

---

## Task 3 — Python Analysis

File: `python/churn_analysis.py`

### Data Wrangling
- Merged 5 PostgreSQL tables + 3 MongoDB collections on `customer_id`
- Handled nulls, duplicates, timezone mismatches, and outliers
- Documented before/after row counts at every step

### Hypothesis Test
- **H0:** Engagement score is the same for churned and retained customers
- **H1:** Retained customers have significantly higher engagement scores
- **Test:** Mann-Whitney U (chosen because engagement scores are not normally distributed — verified with Shapiro-Wilk)
- **Result:** p < 0.05 → Reject H0 → Engagement significantly predicts retention

### RFM Segmentation
Customers scored on Recency, Frequency, and Monetary dimensions (1–4 each):

| Segment | Description | Action |
|---|---|---|
| Champions | High R, F, M | Reward + ask for referrals |
| Loyal Customers | Strong across all | Upsell to higher plan |
| At Risk | High F+M, low R | Immediate win-back campaign |
| Cannot Lose Them | High F, very low R | Personal CS outreach |
| Lost | Low across all | Survey for churn reason |
| Potential Loyalists | Recent, low frequency | Feature education nudges |
| Promising | Recent, low monetary | Free premium trial |
| Needs Attention | Mixed signals | Monitor proactively |

---

## Task 4 — Dashboard

**Tool:** Power BI Desktop

| Visual | Chart Type | Insight |
|---|---|---|
| Churn Rate by Plan Tier | Line Chart | Starter/free churn highest |
| Ticket Volume vs Churn | Scatter Chart | High tickets = high churn risk |
| Engagement: Churned vs Retained | Bar Chart | Retained users far more engaged |
| Customer Segments | Treemap | At-Risk segment largest by count |
| Engagement vs Revenue | Scatter Chart | Combined SQL + MongoDB source |
| Why Customers Churn | Pie Chart | Churn reason breakdown |

**Filters:** Plan Tier (dropdown) + Signup Date (date range)

📊 **[View Dashboard →](https://app.powerbi.com)**
*(replace with your actual published link)*

---

## Task 5 — Video Walkthrough

🎥 **[Watch 5-minute walkthrough →](https://loom.com)**
*(replace with your actual Loom link)*

---

## Recommendations

1. **Early warning system** — Trigger a CS alert when any customer logs
   3+ support tickets in the 30 days before renewal. This is the
   strongest churn signal found in the data.

2. **Free-tier upsell** — The top 20 free-tier users by engagement score
   are prime upgrade candidates. Offer them a 14-day trial of the
   next plan tier.

3. **At-Risk segment outreach** — At-Risk RFM customers have high
   lifetime value but declining engagement. Personal outreach from
   the CS team 60 days before renewal can recover these accounts.

---

## Setup Instructions

### PostgreSQL
```bash
createdb nimbus
psql -U postgres -d nimbus -f nimbus_core.sql
```

### MongoDB
```bash
pip install pymongo
python python/import_mongo_fixed.py
```

### Python Analysis
```bash
pip install -r python/requirements.txt
python python/churn_analysis.py
```

---

| Tool | Version | Purpose |
|---|---|---|
| PostgreSQL | 18 | Relational data storage |
| MongoDB | 7.0 | Event/activity log storage |
| Python | 3.14 | Data wrangling + analysis |
| pandas | 2.0+ | Data manipulation |
| scipy | 1.11+ | Statistical testing |
| scikit-learn | 1.3+ | Segmentation |
| Power BI | Desktop | Dashboard + visualization |

---

## Author
**Komma Sathwik**
Data Analyst Intern Candidate — RoaDo
