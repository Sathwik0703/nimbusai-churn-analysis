-- ============================================================
-- NimbusAI - Churn & Retention Analysis
-- Task 1: SQL Queries (PostgreSQL)
-- Schema: nimbus
-- ============================================================

-- ============================================================
-- Q1: Joins + Aggregation
-- For each subscription plan, calculate:
--   - Number of active customers
--   - Average monthly revenue (MRR)
--   - Support ticket rate (tickets per customer per month)
-- Over the last 6 months
-- ============================================================

SELECT
    p.plan_name,
    p.plan_tier,

    -- Count of distinct active customers on this plan
    COUNT(DISTINCT s.customer_id)                          AS active_customers,

    -- Average MRR across active subscriptions on this plan
    ROUND(AVG(s.mrr_usd), 2)                               AS avg_mrr_usd,

    -- Total tickets raised in last 6 months for these customers
    COUNT(DISTINCT st.ticket_id)                           AS total_tickets,

    -- Ticket rate = total tickets / customers / 6 months
    ROUND(
        COUNT(DISTINCT st.ticket_id)::NUMERIC
        / NULLIF(COUNT(DISTINCT s.customer_id), 0)
        / 6,
    2)                                                     AS tickets_per_customer_per_month

FROM nimbus.plans p

-- Join to subscriptions to get active customers per plan
JOIN nimbus.subscriptions s
    ON s.plan_id = p.plan_id
    AND s.status = 'active'

-- Left join tickets so plans with 0 tickets still appear
LEFT JOIN nimbus.support_tickets st
    ON st.customer_id = s.customer_id
    AND st.created_at >= NOW() - INTERVAL '6 months'

GROUP BY p.plan_id, p.plan_name, p.plan_tier
ORDER BY p.plan_tier, avg_mrr_usd DESC;


-- ============================================================
-- Q2: Window Functions
-- Rank customers within each plan tier by total lifetime value (LTV).
-- LTV = sum of all paid invoice amounts for that customer.
-- Also show % difference between their LTV and the tier average.
-- ============================================================

WITH customer_ltv AS (
    -- Calculate LTV per customer = total amount paid across all invoices
    SELECT
        c.customer_id,
        c.company_name,
        p.plan_tier,
        COALESCE(SUM(bi.amount_usd), 0)  AS lifetime_value
    FROM nimbus.customers c
    JOIN nimbus.subscriptions s
        ON s.customer_id = c.customer_id
    JOIN nimbus.plans p
        ON p.plan_id = s.plan_id
    LEFT JOIN nimbus.billing_invoices bi
        ON bi.customer_id = c.customer_id
        AND bi.status = 'paid'
    GROUP BY c.customer_id, c.company_name, p.plan_tier
)

SELECT
    customer_id,
    company_name,
    plan_tier,
    ROUND(lifetime_value, 2)                               AS lifetime_value_usd,

    -- Rank within each plan tier (1 = highest LTV)
    RANK() OVER (
        PARTITION BY plan_tier
        ORDER BY lifetime_value DESC
    )                                                      AS rank_in_tier,

    -- Average LTV for this tier
    ROUND(AVG(lifetime_value) OVER (
        PARTITION BY plan_tier
    ), 2)                                                  AS tier_avg_ltv,

    -- % difference from tier average
    -- Positive = above average, Negative = below average
    ROUND(
        (lifetime_value - AVG(lifetime_value) OVER (PARTITION BY plan_tier))
        / NULLIF(AVG(lifetime_value) OVER (PARTITION BY plan_tier), 0)
        * 100,
    2)                                                     AS pct_diff_from_tier_avg

FROM customer_ltv
ORDER BY plan_tier, rank_in_tier;


-- ============================================================
-- Q3: CTEs + Subqueries
-- Identify customers who:
--   1. Downgraded their plan in the last 90 days
--   2. Had more than 3 support tickets in the 30 days BEFORE downgrading
-- Include current and previous plan details.
--
-- Logic: A downgrade is when a customer moved to a plan with a
-- lower monthly_price_usd. We detect this by comparing a
-- customer's current subscription plan price vs their previous
-- subscription plan price using created_at ordering.
-- ============================================================

WITH ranked_subscriptions AS (
    -- Rank each customer's subscriptions by creation date
    -- to find current (rank=1) and previous (rank=2)
    SELECT
        s.customer_id,
        s.subscription_id,
        s.plan_id,
        s.status,
        s.created_at                                       AS sub_created_at,
        p.plan_name,
        p.plan_tier,
        p.monthly_price_usd,
        ROW_NUMBER() OVER (
            PARTITION BY s.customer_id
            ORDER BY s.created_at DESC
        )                                                  AS sub_rank
    FROM nimbus.subscriptions s
    JOIN nimbus.plans p ON p.plan_id = s.plan_id
),

downgrades AS (
    -- A downgrade = current plan price < previous plan price
    -- and the current subscription was created in the last 90 days
    SELECT
        curr.customer_id,
        curr.plan_name                                     AS current_plan,
        curr.plan_tier                                     AS current_tier,
        curr.monthly_price_usd                             AS current_price,
        curr.sub_created_at                                AS downgrade_date,
        prev.plan_name                                     AS previous_plan,
        prev.plan_tier                                     AS previous_tier,
        prev.monthly_price_usd                             AS previous_price
    FROM ranked_subscriptions curr
    JOIN ranked_subscriptions prev
        ON prev.customer_id = curr.customer_id
        AND prev.sub_rank = 2
    WHERE curr.sub_rank = 1
      AND curr.monthly_price_usd < prev.monthly_price_usd
      AND curr.sub_created_at >= NOW() - INTERVAL '90 days'
),

high_ticket_customers AS (
    -- Customers with more than 3 tickets in the 30 days
    -- before their downgrade date
    SELECT
        d.customer_id,
        COUNT(st.ticket_id)                                AS tickets_before_downgrade
    FROM downgrades d
    JOIN nimbus.support_tickets st
        ON st.customer_id = d.customer_id
        AND st.created_at >= d.downgrade_date - INTERVAL '30 days'
        AND st.created_at <  d.downgrade_date
    GROUP BY d.customer_id
    HAVING COUNT(st.ticket_id) > 3
)

SELECT
    d.customer_id,
    c.company_name,
    c.contact_email,
    d.downgrade_date,
    d.previous_plan,
    d.previous_tier,
    d.previous_price                                       AS previous_monthly_price_usd,
    d.current_plan,
    d.current_tier,
    d.current_price                                        AS current_monthly_price_usd,
    h.tickets_before_downgrade
FROM downgrades d
JOIN high_ticket_customers h
    ON h.customer_id = d.customer_id
JOIN nimbus.customers c
    ON c.customer_id = d.customer_id
ORDER BY d.downgrade_date DESC;


-- ============================================================
-- Q4: Time Series
-- Calculate month-over-month growth rate of new subscriptions
-- and rolling 3-month average churn rate, by plan tier.
-- Flag months where churn exceeded 2x the rolling average.
-- ============================================================

WITH monthly_stats AS (
    -- Count new subscriptions and churned subscriptions per month per tier
    SELECT
        DATE_TRUNC('month', s.created_at)                  AS month,
        p.plan_tier,

        -- New subscriptions started this month
        COUNT(CASE WHEN s.status != 'cancelled' OR s.created_at >= DATE_TRUNC('month', s.created_at)
                   THEN s.subscription_id END)             AS new_subscriptions,

        -- Churned = cancelled subscriptions where end_date falls in this month
        COUNT(CASE WHEN s.status = 'cancelled'
                    AND DATE_TRUNC('month', s.end_date) = DATE_TRUNC('month', s.created_at)
                   THEN s.subscription_id END)             AS churned_subscriptions,

        COUNT(s.subscription_id)                           AS total_subscriptions

    FROM nimbus.subscriptions s
    JOIN nimbus.plans p ON p.plan_id = s.plan_id
    GROUP BY DATE_TRUNC('month', s.created_at), p.plan_tier
),

with_churn_rate AS (
    SELECT
        month,
        plan_tier,
        new_subscriptions,
        churned_subscriptions,
        total_subscriptions,

        -- Churn rate = churned / total for that month
        ROUND(
            churned_subscriptions::NUMERIC
            / NULLIF(total_subscriptions, 0) * 100,
        2)                                                 AS churn_rate_pct,

        -- MoM growth = (this month new - last month new) / last month new * 100
        ROUND(
            (new_subscriptions - LAG(new_subscriptions) OVER (
                PARTITION BY plan_tier ORDER BY month
            ))::NUMERIC
            / NULLIF(LAG(new_subscriptions) OVER (
                PARTITION BY plan_tier ORDER BY month
            ), 0) * 100,
        2)                                                 AS mom_growth_pct

    FROM monthly_stats
),

with_rolling_avg AS (
    SELECT
        *,
        -- Rolling 3-month average churn rate
        ROUND(AVG(churn_rate_pct) OVER (
            PARTITION BY plan_tier
            ORDER BY month
            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
        ), 2)                                              AS rolling_3m_avg_churn

    FROM with_churn_rate
)

SELECT
    TO_CHAR(month, 'YYYY-MM')                             AS month,
    plan_tier,
    new_subscriptions,
    churned_subscriptions,
    churn_rate_pct,
    mom_growth_pct,
    rolling_3m_avg_churn,

    -- Flag if churn this month exceeded 2x the rolling average
    CASE
        WHEN churn_rate_pct > 2 * rolling_3m_avg_churn
        THEN 'FLAGGED - High Churn'
        ELSE 'Normal'
    END                                                    AS churn_alert

FROM with_rolling_avg
ORDER BY plan_tier, month;


-- ============================================================
-- Q5: Advanced - Duplicate Customer Detection
-- Detect potential duplicate accounts based on:
--   1. Similar company names (using pg_trgm similarity)
--   2. Same email domain
--   3. Overlapping team members (same email in team_members)
--
-- Matching logic:
--   - We use trigram similarity (similarity() from pg_trgm) on
--     company_name. A score > 0.5 means names are very similar.
--   - We extract email domain using SPLIT_PART and match on it.
--   - We check if two customers share any team member emails.
--   - A pair is flagged as a likely duplicate if it matches
--     on at least 2 of the 3 signals above.
-- ============================================================

-- Enable trigram extension if not already enabled
CREATE EXTENSION IF NOT EXISTS pg_trgm;

WITH customer_pairs AS (
    -- Self-join customers to find all pairs (avoid duplicates with c1.id < c2.id)
    SELECT
        c1.customer_id                                     AS customer_id_1,
        c1.company_name                                    AS company_name_1,
        c1.contact_email                                   AS email_1,
        c2.customer_id                                     AS customer_id_2,
        c2.company_name                                    AS company_name_2,
        c2.contact_email                                   AS email_2,

        -- Signal 1: Name similarity score (0 to 1, higher = more similar)
        ROUND(similarity(c1.company_name, c2.company_name)::NUMERIC, 2)
                                                           AS name_similarity,

        -- Signal 2: Do they share the same email domain?
        CASE
            WHEN SPLIT_PART(c1.contact_email, '@', 2)
               = SPLIT_PART(c2.contact_email, '@', 2)
            THEN TRUE ELSE FALSE
        END                                                AS same_email_domain

    FROM nimbus.customers c1
    JOIN nimbus.customers c2
        ON c1.customer_id < c2.customer_id  -- avoid duplicate pairs
),

shared_members AS (
    -- Signal 3: Find customer pairs that share team member emails
    SELECT DISTINCT
        tm1.customer_id                                    AS customer_id_1,
        tm2.customer_id                                    AS customer_id_2,
        TRUE                                               AS has_shared_members
    FROM nimbus.team_members tm1
    JOIN nimbus.team_members tm2
        ON tm1.email = tm2.email
        AND tm1.customer_id < tm2.customer_id
),

scored_pairs AS (
    SELECT
        cp.*,
        COALESCE(sm.has_shared_members, FALSE)             AS has_shared_members,

        -- Count how many signals matched (max 3)
        (CASE WHEN cp.name_similarity > 0.5  THEN 1 ELSE 0 END
       + CASE WHEN cp.same_email_domain       THEN 1 ELSE 0 END
       + CASE WHEN sm.has_shared_members      THEN 1 ELSE 0 END)
                                                           AS match_signals

    FROM customer_pairs cp
    LEFT JOIN shared_members sm
        ON sm.customer_id_1 = cp.customer_id_1
        AND sm.customer_id_2 = cp.customer_id_2
)

SELECT
    customer_id_1,
    company_name_1,
    email_1,
    customer_id_2,
    company_name_2,
    email_2,
    name_similarity,
    same_email_domain,
    has_shared_members,
    match_signals,
    CASE
        WHEN match_signals >= 2 THEN 'Likely Duplicate'
        WHEN match_signals = 1  THEN 'Possible Duplicate'
        ELSE 'Unlikely'
    END                                                    AS duplicate_assessment

FROM scored_pairs
WHERE match_signals >= 1
ORDER BY match_signals DESC, name_similarity DESC;