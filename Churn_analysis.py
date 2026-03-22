# ============================================================
# NimbusAI - Churn & Retention Analysis
# Task 3: Data Wrangling, Hypothesis Testing & Segmentation
# Run: python churn_analysis.py
# OR open as Jupyter: jupyter notebook (rename to .ipynb)
# ============================================================

import psycopg2
import pymongo
import pandas as pd
import numpy as np
from scipy import stats
from sklearn.preprocessing import MinMaxScaler
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import seaborn as sns
import warnings
from datetime import datetime, timezone

warnings.filterwarnings('ignore')
pd.set_option('display.max_columns', None)
pd.set_option('display.width', 120)

print("=" * 60)
print("  NimbusAI Churn & Retention Analysis — Task 3")
print("=" * 60)

# ============================================================
# SECTION 1 — CONNECT & EXTRACT DATA
# ============================================================
print("\n── SECTION 1: Connecting to Databases ──────────────────")

# --- PostgreSQL Connection ---
try:
    pg_conn = psycopg2.connect(
        dbname   = "nimbus",
        user     = "postgres",
        password = "Komma@7777",
        host     = "localhost",
        port     = "5432"
    )
    print("✓ PostgreSQL connected")
except Exception as e:
    print(f"✗ PostgreSQL error: {e}")
    raise

# --- MongoDB Connection ---
try:
    mongo_client = pymongo.MongoClient("mongodb://localhost:27017/")
    mongo_db     = mongo_client["nimbus_events"]
    print("✓ MongoDB connected")
except Exception as e:
    print(f"✗ MongoDB error: {e}")
    raise

# --- Extract SQL Tables ---
print("\n→ Extracting PostgreSQL tables...")

df_customers = pd.read_sql("""
    SELECT customer_id, company_name, industry, company_size,
           country_name, signup_date, signup_source,
           is_active, churned_at, churn_reason,
           nps_score, created_at
    FROM nimbus.customers
""", pg_conn)

df_subscriptions = pd.read_sql("""
    SELECT subscription_id, customer_id, plan_id, status,
           billing_cycle, start_date, end_date,
           mrr_usd, discount_pct, cancellation_reason, created_at
    FROM nimbus.subscriptions
""", pg_conn)

df_plans = pd.read_sql("""
    SELECT plan_id, plan_name, plan_tier, monthly_price_usd
    FROM nimbus.plans
""", pg_conn)

df_tickets = pd.read_sql("""
    SELECT ticket_id, customer_id, category, priority,
           status, created_at, resolved_at,
           satisfaction_score, escalated
    FROM nimbus.support_tickets
""", pg_conn)

df_invoices = pd.read_sql("""
    SELECT invoice_id, customer_id, amount_usd,
           total_usd, status, invoice_date, paid_at
    FROM nimbus.billing_invoices
""", pg_conn)

print(f"  ✓ customers:      {len(df_customers):,} rows")
print(f"  ✓ subscriptions:  {len(df_subscriptions):,} rows")
print(f"  ✓ plans:          {len(df_plans):,} rows")
print(f"  ✓ tickets:        {len(df_tickets):,} rows")
print(f"  ✓ invoices:       {len(df_invoices):,} rows")

# --- Extract MongoDB Collections ---
print("\n→ Extracting MongoDB collections...")

df_activity = pd.DataFrame(list(
    mongo_db.user_activity_logs.find({}, {"_id": 0})
))
df_onboarding = pd.DataFrame(list(
    mongo_db.onboarding_events.find({}, {"_id": 0})
))
df_nps = pd.DataFrame(list(
    mongo_db.nps_survey_responses.find({}, {"_id": 0})
))

print(f"  ✓ user_activity_logs:    {len(df_activity):,} rows")
print(f"  ✓ onboarding_events:     {len(df_onboarding):,} rows")
print(f"  ✓ nps_survey_responses:  {len(df_nps):,} rows")

# ============================================================
# SECTION 2 — MERGE & CLEAN
# ============================================================
print("\n── SECTION 2: Merging & Cleaning ────────────────────────")

# ── 2.1 CUSTOMERS + SUBSCRIPTIONS + PLANS ──

print("\n→ Step 1: Merge customers + subscriptions + plans")
before = len(df_customers)

# Keep latest subscription per customer
df_subs_latest = (
    df_subscriptions
    .sort_values("created_at", ascending=False)
    .drop_duplicates(subset="customer_id", keep="first")
)

df_main = (
    df_customers
    .merge(df_subs_latest[["customer_id","plan_id","status",
                            "billing_cycle","mrr_usd",
                            "discount_pct","cancellation_reason",
                            "start_date","end_date"]],
           on="customer_id", how="left")
    .merge(df_plans[["plan_id","plan_name","plan_tier",
                     "monthly_price_usd"]],
           on="plan_id", how="left")
)

print(f"  Before: {before:,} rows → After merge: {len(df_main):,} rows")

# ── 2.2 HANDLE NULLS ──

print("\n→ Step 2: Handle nulls")
null_before = df_main.isnull().sum().sum()

# mrr_usd null = likely free tier, fill with 0
df_main["mrr_usd"] = df_main["mrr_usd"].fillna(0)
df_main["discount_pct"] = df_main["discount_pct"].fillna(0)
df_main["monthly_price_usd"] = df_main["monthly_price_usd"].fillna(0)

# plan_tier null = fill as 'unknown'
df_main["plan_tier"] = df_main["plan_tier"].fillna("unknown")
df_main["plan_name"] = df_main["plan_name"].fillna("unknown")
df_main["billing_cycle"] = df_main["billing_cycle"].fillna("unknown")
df_main["cancellation_reason"] = df_main["cancellation_reason"].fillna("none")
df_main["churn_reason"] = df_main["churn_reason"].fillna("none")
df_main["industry"] = df_main["industry"].fillna("unknown")
df_main["company_size"] = df_main["company_size"].fillna("unknown")
df_main["nps_score"] = df_main["nps_score"].fillna(
    df_main["nps_score"].median()
)

null_after = df_main.isnull().sum().sum()
print(f"  Nulls before: {null_before:,} → after: {null_after:,}")

# ── 2.3 FIX DATA TYPES & TIMEZONES ──

print("\n→ Step 3: Fix data types and timezones")

# Convert all date columns to UTC-aware datetime
date_cols_pg = ["signup_date","churned_at","start_date","end_date","created_at"]
for col in date_cols_pg:
    if col in df_main.columns:
        df_main[col] = pd.to_datetime(df_main[col], utc=True, errors="coerce")

# Fix MongoDB timestamps — mixed formats (ISODate string + plain string)
for col in ["timestamp"]:
    if col in df_activity.columns:
        df_activity[col] = pd.to_datetime(
            df_activity[col], utc=True, errors="coerce"
        )

for col in ["timestamp"]:
    if col in df_onboarding.columns:
        df_onboarding[col] = pd.to_datetime(
            df_onboarding[col], utc=True, errors="coerce"
        )

for col in ["survey_date"]:
    if col in df_nps.columns:
        df_nps[col] = pd.to_datetime(
            df_nps[col], utc=True, errors="coerce"
        )

print("  ✓ All timestamps normalized to UTC")

# ── 2.4 REMOVE DUPLICATES ──

print("\n→ Step 4: Remove duplicates")

dup_customers = df_main.duplicated(subset="customer_id").sum()
df_main = df_main.drop_duplicates(subset="customer_id", keep="first")
print(f"  Duplicate customers removed: {dup_customers}")

dup_tickets = df_tickets.duplicated(
    subset=["customer_id","created_at","category"]
).sum()
df_tickets = df_tickets.drop_duplicates(
    subset=["customer_id","created_at","category"], keep="first"
)
print(f"  Duplicate tickets removed: {dup_tickets}")

dup_activity = df_activity.duplicated(
    subset=["member_id","timestamp","event_type"]
).sum()
df_activity = df_activity.drop_duplicates(
    subset=["member_id","timestamp","event_type"], keep="first"
)
print(f"  Duplicate activity events removed: {dup_activity}")

# ── 2.5 HANDLE OUTLIERS ──

print("\n→ Step 5: Handle outliers")

# Cap MRR at 99th percentile to remove extreme billing errors
mrr_cap = df_main["mrr_usd"].quantile(0.99)
outliers_mrr = (df_main["mrr_usd"] > mrr_cap).sum()
df_main["mrr_usd"] = df_main["mrr_usd"].clip(upper=mrr_cap)
print(f"  MRR outliers capped (>{mrr_cap:.0f}): {outliers_mrr} rows")

# Cap session duration at 99th percentile
if "session_duration_sec" in df_activity.columns:
    dur_cap = df_activity["session_duration_sec"].quantile(0.99)
    dur_outliers = (df_activity["session_duration_sec"] > dur_cap).sum()
    df_activity["session_duration_sec"] = df_activity[
        "session_duration_sec"
    ].clip(upper=dur_cap)
    print(f"  Session duration outliers capped: {dur_outliers} rows")

# ── 2.6 COMPUTE ENGAGEMENT FEATURES FROM MONGODB ──

print("\n→ Step 6: Compute engagement features from MongoDB")

# Total events per customer
engagement = (
    df_activity
    .groupby("customer_id")
    .agg(
        total_events        = ("event_type", "count"),
        unique_days_active  = ("timestamp",
                               lambda x: x.dt.date.nunique()),
        avg_session_dur_sec = ("session_duration_sec", "mean"),
        unique_features     = ("event_type", "nunique")
    )
    .reset_index()
)

# Engagement score (same formula as MongoDB Q4)
engagement["engagement_score"] = (
    engagement["total_events"]        * 0.4 +
    engagement["unique_days_active"]  * 0.3 +
    (engagement["avg_session_dur_sec"] / 60) * 0.2 +
    engagement["unique_features"]     * 0.1
).round(2)

print(f"  ✓ Engagement features computed for "
      f"{len(engagement):,} customers")

# ── 2.7 COMPUTE TICKET FEATURES ──

ticket_features = (
    df_tickets
    .groupby("customer_id")
    .agg(
        total_tickets    = ("ticket_id",  "count"),
        escalated_count  = ("escalated",  "sum"),
        avg_satisfaction = ("satisfaction_score", "mean")
    )
    .reset_index()
)

# ── 2.8 COMPUTE LTV FROM INVOICES ──

ltv = (
    df_invoices[df_invoices["status"] == "paid"]
    .groupby("customer_id")
    .agg(lifetime_value = ("amount_usd", "sum"))
    .reset_index()
)

# ── 2.9 FINAL MERGE — ALL FEATURES ──

print("\n→ Step 7: Final merge of all features")

df_final = (
    df_main
    .merge(engagement,     on="customer_id", how="left")
    .merge(ticket_features,on="customer_id", how="left")
    .merge(ltv,            on="customer_id", how="left")
)

# Fill engagement/ticket nulls with 0 (no activity = 0)
fill_zero_cols = [
    "total_events","unique_days_active","avg_session_dur_sec",
    "unique_features","engagement_score","total_tickets",
    "escalated_count","avg_satisfaction","lifetime_value"
]
for col in fill_zero_cols:
    if col in df_final.columns:
        df_final[col] = df_final[col].fillna(0)

# Create churn flag
df_final["is_churned"] = df_final["churned_at"].notna().astype(int)

print(f"  ✓ Final dataset: {len(df_final):,} rows × "
      f"{len(df_final.columns)} columns")
print(f"  ✓ Churned customers: "
      f"{df_final['is_churned'].sum():,} "
      f"({df_final['is_churned'].mean()*100:.1f}%)")
print(f"  ✓ Active customers:  "
      f"{(df_final['is_churned']==0).sum():,}")
print(f"\n  Columns: {list(df_final.columns)}")

# ── 2.10 SAVE CLEANED DATA ──

df_final.to_csv("nimbus_cleaned.csv", index=False)
print("\n  ✓ Saved cleaned data to nimbus_cleaned.csv")

# ============================================================
# SECTION 3 — HYPOTHESIS TESTING
# ============================================================
print("\n── SECTION 3: Hypothesis Testing ────────────────────────")

print("""
Hypothesis:
  H0: Engagement score is the same for churned and retained customers
  H1: Retained customers have significantly higher engagement scores
  
  Significance level: α = 0.05
  Test chosen: Mann-Whitney U (non-parametric)
  
  Reason for Mann-Whitney U:
    - Engagement scores are not normally distributed (right-skewed)
    - Many customers have zero activity (free tier)
    - Mann-Whitney does NOT assume normality — safer than t-test
    - It tests whether one group tends to have higher values
""")

churned  = df_final[df_final["is_churned"] == 1]["engagement_score"]
retained = df_final[df_final["is_churned"] == 0]["engagement_score"]

print(f"  Churned  customers: n={len(churned):,}, "
      f"median score={churned.median():.2f}")
print(f"  Retained customers: n={len(retained):,}, "
      f"median score={retained.median():.2f}")

# Check normality (Shapiro on sample of 500)
sample_c = churned.sample(min(500, len(churned)),   random_state=42)
sample_r = retained.sample(min(500, len(retained)), random_state=42)
_, p_norm_c = stats.shapiro(sample_c)
_, p_norm_r = stats.shapiro(sample_r)
print(f"\n  Normality check (Shapiro-Wilk):")
print(f"    Churned  p={p_norm_c:.4f} "
      f"→ {'NOT normal' if p_norm_c < 0.05 else 'normal'}")
print(f"    Retained p={p_norm_r:.4f} "
      f"→ {'NOT normal' if p_norm_r < 0.05 else 'normal'}")
print(f"  → Mann-Whitney U is the correct test ✓")

# Run Mann-Whitney U test
stat, p_value = stats.mannwhitneyu(
    retained, churned, alternative="greater"
)

print(f"\n  Mann-Whitney U statistic: {stat:,.0f}")
print(f"  P-value: {p_value:.6f}")
print(f"\n  Conclusion:")
if p_value < 0.05:
    print(f"  ✓ REJECT H0 (p={p_value:.4f} < 0.05)")
    print(f"  ✓ Retained customers have significantly HIGHER")
    print(f"    engagement scores than churned customers.")
    print(f"  ✓ Business insight: Engagement is a strong predictor")
    print(f"    of retention — invest in feature adoption programs.")
else:
    print(f"  ✗ FAIL TO REJECT H0 (p={p_value:.4f} >= 0.05)")
    print(f"  ✗ No significant difference in engagement scores.")

# Plot hypothesis test
fig, axes = plt.subplots(1, 2, figsize=(12, 4))

# Box plot
axes[0].boxplot(
    [churned.values, retained.values],
    labels=["Churned", "Retained"],
    patch_artist=True,
    boxprops=dict(facecolor="#FF6B6B", color="gray"),
    medianprops=dict(color="white", linewidth=2)
)
axes[0].set_title("Engagement Score: Churned vs Retained")
axes[0].set_ylabel("Engagement Score")

# Distribution plot
axes[1].hist(churned,  bins=30, alpha=0.6, color="#FF6B6B",
             label="Churned",  density=True)
axes[1].hist(retained, bins=30, alpha=0.6, color="#4ECDC4",
             label="Retained", density=True)
axes[1].axvline(churned.median(),  color="#FF6B6B",
                linestyle="--", label=f"Churned median: {churned.median():.1f}")
axes[1].axvline(retained.median(), color="#4ECDC4",
                linestyle="--", label=f"Retained median: {retained.median():.1f}")
axes[1].set_title("Engagement Score Distribution")
axes[1].set_xlabel("Engagement Score")
axes[1].legend(fontsize=8)

plt.suptitle(f"Hypothesis Test: p={p_value:.4f} "
             f"({'Significant' if p_value < 0.05 else 'Not significant'})",
             fontsize=12, fontweight="bold")
plt.tight_layout()
plt.savefig("hypothesis_test.png", dpi=150, bbox_inches="tight")
plt.show()
print("\n  ✓ Saved hypothesis_test.png")

# ============================================================
# SECTION 4 — CUSTOMER SEGMENTATION (RFM)
# ============================================================
print("\n── SECTION 4: RFM Segmentation ──────────────────────────")

print("""
RFM Segmentation:
  R (Recency)   = Days since last activity (lower = better)
  F (Frequency) = Total events / interactions
  M (Monetary)  = Lifetime value (paid invoices)
  
  Each dimension scored 1-4 (4 = best)
  Combined into RFM segments with business labels
""")

# Reference date = today
ref_date = pd.Timestamp.now(tz="UTC")

# Calculate last activity date per customer from MongoDB
last_activity = (
    df_activity
    .groupby("customer_id")["timestamp"]
    .max()
    .reset_index()
    .rename(columns={"timestamp": "last_activity_date"})
)

df_rfm = df_final.merge(last_activity, on="customer_id", how="left")

# If no activity, use signup_date as fallback
df_rfm["last_activity_date"] = df_rfm["last_activity_date"].fillna(
    df_rfm["signup_date"]
)

# Ensure timezone consistency
df_rfm["last_activity_date"] = pd.to_datetime(
    df_rfm["last_activity_date"], utc=True, errors="coerce"
)

# Calculate RFM values
df_rfm["recency_days"] = (
    ref_date - df_rfm["last_activity_date"]
).dt.days.fillna(999)

df_rfm["frequency"]  = df_rfm["total_events"].fillna(0)
df_rfm["monetary"]   = df_rfm["lifetime_value"].fillna(0)

# Score each dimension into quartiles 1-4
# Recency: LOWER days = BETTER → reverse scoring
df_rfm["r_score"] = pd.qcut(
    df_rfm["recency_days"].rank(method="first"),
    q=4, labels=[4, 3, 2, 1]
).astype(int)

# Frequency: HIGHER = BETTER
df_rfm["f_score"] = pd.qcut(
    df_rfm["frequency"].rank(method="first"),
    q=4, labels=[1, 2, 3, 4]
).astype(int)

# Monetary: HIGHER = BETTER
df_rfm["m_score"] = pd.qcut(
    df_rfm["monetary"].rank(method="first"),
    q=4, labels=[1, 2, 3, 4]
).astype(int)

# Combined RFM score
df_rfm["rfm_score"] = (
    df_rfm["r_score"].astype(str) +
    df_rfm["f_score"].astype(str) +
    df_rfm["m_score"].astype(str)
)

df_rfm["rfm_total"] = (
    df_rfm["r_score"] +
    df_rfm["f_score"] +
    df_rfm["m_score"]
)

# Assign segments
def assign_segment(row):
    r, f, m = row["r_score"], row["f_score"], row["m_score"]
    if r >= 4 and f >= 4 and m >= 4:
        return "Champions"
    elif r >= 3 and f >= 3 and m >= 3:
        return "Loyal Customers"
    elif r >= 3 and f <= 2:
        return "Potential Loyalists"
    elif r <= 2 and f >= 3 and m >= 3:
        return "At Risk"
    elif r == 1 and f >= 3:
        return "Cannot Lose Them"
    elif r <= 2 and f <= 2 and m <= 2:
        return "Lost"
    elif r >= 3 and m <= 2:
        return "Promising"
    else:
        return "Needs Attention"

df_rfm["segment"] = df_rfm.apply(assign_segment, axis=1)

# Print segment summary
seg_summary = (
    df_rfm.groupby("segment")
    .agg(
        count          = ("customer_id", "count"),
        avg_ltv        = ("monetary",    "mean"),
        avg_engagement = ("engagement_score", "mean"),
        churn_rate     = ("is_churned",  "mean")
    )
    .round(2)
    .sort_values("avg_ltv", ascending=False)
)
seg_summary["churn_rate"] = (seg_summary["churn_rate"] * 100).round(1)
seg_summary.columns = ["Count", "Avg LTV ($)", "Avg Engagement", "Churn Rate (%)"]

print("\n  RFM Segment Summary:")
print(seg_summary.to_string())

# Print business implications
print("""
  Business Implications:
  ┌─────────────────────┬──────────────────────────────────────────┐
  │ Champions           │ Reward them, ask for referrals           │
  │ Loyal Customers     │ Upsell to higher plans                   │
  │ At Risk             │ Send win-back campaigns immediately       │
  │ Cannot Lose Them    │ Personal outreach from CS team           │
  │ Lost                │ Survey for churn reason, low priority    │
  │ Potential Loyalists │ Onboarding nudges, feature education     │
  │ Promising           │ Free trials of premium features          │
  │ Needs Attention     │ Monitor closely, check in proactively    │
  └─────────────────────┴──────────────────────────────────────────┘
""")

# Save segments
df_rfm[["customer_id","company_name","plan_tier","segment",
        "r_score","f_score","m_score","rfm_total",
        "recency_days","frequency","monetary",
        "engagement_score","is_churned"]].to_csv(
    "rfm_segments.csv", index=False
)
print("  ✓ Saved RFM segments to rfm_segments.csv")

# ── PLOT SEGMENTS ──

fig, axes = plt.subplots(1, 3, figsize=(16, 5))

# 1. Segment distribution
seg_counts = df_rfm["segment"].value_counts()
colors = ["#4ECDC4","#45B7D1","#96CEB4","#FFEAA7",
          "#DDA0DD","#FF6B6B","#98D8C8","#F7DC6F"]
axes[0].barh(seg_counts.index, seg_counts.values,
             color=colors[:len(seg_counts)])
axes[0].set_title("Customers per Segment")
axes[0].set_xlabel("Count")

# 2. Churn rate by segment
churn_by_seg = df_rfm.groupby("segment")["is_churned"].mean() * 100
churn_by_seg = churn_by_seg.sort_values(ascending=False)
bar_colors   = ["#FF6B6B" if x > 30 else "#4ECDC4"
                for x in churn_by_seg.values]
axes[1].bar(range(len(churn_by_seg)), churn_by_seg.values,
            color=bar_colors)
axes[1].set_xticks(range(len(churn_by_seg)))
axes[1].set_xticklabels(churn_by_seg.index, rotation=45, ha="right",
                        fontsize=8)
axes[1].set_title("Churn Rate by Segment (%)")
axes[1].set_ylabel("Churn Rate (%)")
axes[1].axhline(df_rfm["is_churned"].mean() * 100,
                color="gray", linestyle="--",
                label="Overall avg")
axes[1].legend(fontsize=8)

# 3. Avg LTV by segment
ltv_by_seg = df_rfm.groupby("segment")["monetary"].mean().sort_values(
    ascending=False
)
axes[2].bar(range(len(ltv_by_seg)), ltv_by_seg.values,
            color="#45B7D1")
axes[2].set_xticks(range(len(ltv_by_seg)))
axes[2].set_xticklabels(ltv_by_seg.index, rotation=45, ha="right",
                        fontsize=8)
axes[2].set_title("Average LTV by Segment ($)")
axes[2].set_ylabel("Avg LTV ($)")

plt.suptitle("RFM Customer Segmentation — NimbusAI",
             fontsize=13, fontweight="bold")
plt.tight_layout()
plt.savefig("rfm_segments.png", dpi=150, bbox_inches="tight")
plt.show()
print("  ✓ Saved rfm_segments.png")

# ============================================================
# FINAL SUMMARY
# ============================================================
print("\n" + "=" * 60)
print("  TASK 3 COMPLETE")
print("=" * 60)
print(f"""
  Files saved:
    • nimbus_cleaned.csv   — merged, cleaned dataset
    • rfm_segments.csv     — customer segments for dashboard
    • hypothesis_test.png  — test visualization
    • rfm_segments.png     — segmentation charts

  Key findings:
    • Total customers analyzed: {len(df_final):,}
    • Overall churn rate: {df_final['is_churned'].mean()*100:.1f}%
    • Hypothesis test p-value: {p_value:.4f}
      → Engagement {'IS' if p_value < 0.05 else 'is NOT'} a
        significant predictor of retention
    • RFM segments created: {df_rfm['segment'].nunique()}
    • Highest risk segment: {churn_by_seg.index[0]}
      ({churn_by_seg.iloc[0]:.1f}% churn rate)
""")

pg_conn.close()
mongo_client.close()
print("✓ Database connections closed.")
print("✓ Ready for Task 4 — Dashboard!")