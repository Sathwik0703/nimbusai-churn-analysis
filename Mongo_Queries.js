// ============================================================
// NimbusAI - Churn & Retention Analysis
// Task 2: MongoDB Aggregation Pipelines
// Database: nimbus_events
// Collections: user_activity_logs, onboarding_events, nps_survey_responses
// Run in: MongoDB Compass > nimbus_events > [collection] > Aggregations
// ============================================================


// ============================================================
// Q1: Aggregation Pipeline
// Average sessions per user per week, by subscription tier.
// + 25th, 50th, 75th percentile of session_duration_sec.
//
// NOTE: user_activity_logs does not have plan_tier directly.
// We group by customer_id as a proxy (tier join done in Python
// Task 3 via customer_id → subscriptions → plans).
// Here we compute weekly session stats per customer.
// ============================================================

// Run on: nimbus_events.user_activity_logs
db.user_activity_logs.aggregate([

  // Step 1: Parse timestamp and extract week + year
  {
    $addFields: {
      parsed_ts: { $toDate: "$timestamp" }
    }
  },

  // Step 2: Group by customer + member + week to count sessions
  {
    $group: {
      _id: {
        customer_id:  "$customer_id",
        member_id:    "$member_id",
        year:         { $isoWeekYear: { $toDate: "$timestamp" } },
        week:         { $isoWeek:     { $toDate: "$timestamp" } }
      },
      sessions_that_week:   { $sum: 1 },
      durations_that_week:  { $push: "$session_duration_sec" }
    }
  },

  // Step 3: Group by customer to get avg sessions per week
  {
    $group: {
      _id: "$_id.customer_id",
      avg_sessions_per_week: { $avg: "$sessions_that_week" },
      all_durations: {
        $push: {
          $filter: {
            input: "$durations_that_week",
            as:    "d",
            cond:  { $ne: ["$$d", null] }
          }
        }
      }
    }
  },

  // Step 4: Flatten nested duration arrays
  {
    $addFields: {
      flat_durations: {
        $reduce: {
          input:       "$all_durations",
          initialValue: [],
          in: { $concatArrays: ["$$value", "$$this"] }
        }
      }
    }
  },

  // Step 5: Sort durations for percentile calculation
  {
    $addFields: {
      sorted_durations: { $sortArray: { input: "$flat_durations", sortBy: 1 } }
    }
  },

  // Step 6: Calculate p25, p50, p75 using array index math
  {
    $addFields: {
      total_count: { $size: "$sorted_durations" },
      p25_index: {
        $floor: {
          $multiply: [0.25, { $size: "$sorted_durations" }]
        }
      },
      p50_index: {
        $floor: {
          $multiply: [0.50, { $size: "$sorted_durations" }]
        }
      },
      p75_index: {
        $floor: {
          $multiply: [0.75, { $size: "$sorted_durations" }]
        }
      }
    }
  },

  {
    $addFields: {
      p25_duration_sec: {
        $arrayElemAt: ["$sorted_durations", "$p25_index"]
      },
      p50_duration_sec: {
        $arrayElemAt: ["$sorted_durations", "$p50_index"]
      },
      p75_duration_sec: {
        $arrayElemAt: ["$sorted_durations", "$p75_index"]
      }
    }
  },

  // Step 7: Clean up output
  {
    $project: {
      _id:                   0,
      customer_id:           "$_id",
      avg_sessions_per_week: { $round: ["$avg_sessions_per_week", 2] },
      total_events:          "$total_count",
      p25_duration_sec:      1,
      p50_duration_sec:      1,
      p75_duration_sec:      1
    }
  },

  { $sort: { avg_sessions_per_week: -1 } }
])


// ============================================================
// Q2: Event Analysis
// For each event_type (product feature), compute:
//   - Daily Active Users (DAU) = unique users per day
//   - 7-day retention rate = users who used the feature again
//     within 7 days of their first use
// ============================================================

// Run on: nimbus_events.user_activity_logs
db.user_activity_logs.aggregate([

  // Step 1: Add date field (just the date part, no time)
  {
    $addFields: {
      event_date: {
        $dateToString: {
          format: "%Y-%m-%d",
          date:   { $toDate: "$timestamp" }
        }
      }
    }
  },

  // Step 2: Find first use date per user per event_type
  {
    $group: {
      _id: {
        event_type: "$event_type",
        member_id:  "$member_id"
      },
      first_use_date: { $min: { $toDate: "$timestamp" } },
      all_use_dates:  { $addToSet: { $toDate: "$timestamp" } }
    }
  },

  // Step 3: Check if user came back within 7 days of first use
  {
    $addFields: {
      seven_day_cutoff: {
        $dateAdd: {
          startDate: "$first_use_date",
          unit:      "day",
          amount:    7
        }
      },
      returned_within_7_days: {
        $gt: [
          {
            $size: {
              $filter: {
                input: "$all_use_dates",
                as:    "d",
                cond: {
                  $and: [
                    { $gt: ["$$d", "$first_use_date"] },
                    {
                      $lte: [
                        "$$d",
                        {
                          $dateAdd: {
                            startDate: "$first_use_date",
                            unit:      "day",
                            amount:    7
                          }
                        }
                      ]
                    }
                  ]
                }
              }
            }
          },
          0
        ]
      }
    }
  },

  // Step 4: Group by event_type to get DAU and retention
  {
    $group: {
      _id:                   "$_id.event_type",
      total_unique_users:    { $sum: 1 },
      retained_users:        {
        $sum: { $cond: ["$returned_within_7_days", 1, 0] }
      },
      earliest_date:         { $min: "$first_use_date" },
      latest_date:           { $max: "$first_use_date" }
    }
  },

  // Step 5: Calculate DAU and retention rate
  {
    $addFields: {
      days_span: {
        $add: [
          1,
          {
            $divide: [
              { $subtract: ["$latest_date", "$earliest_date"] },
              86400000  // ms in a day
            ]
          }
        ]
      },
      retention_rate_pct: {
        $round: [
          {
            $multiply: [
              { $divide: ["$retained_users", { $max: ["$total_unique_users", 1] }] },
              100
            ]
          },
          2
        ]
      }
    }
  },

  {
    $addFields: {
      avg_dau: {
        $round: [
          { $divide: ["$total_unique_users", { $max: ["$days_span", 1] }] },
          2
        ]
      }
    }
  },

  // Step 6: Final output
  {
    $project: {
      _id:                0,
      event_type:         "$_id",
      total_unique_users: 1,
      avg_dau:            1,
      retained_users:     1,
      retention_rate_pct: 1
    }
  },

  { $sort: { retention_rate_pct: -1 } }
])


// ============================================================
// Q3: Funnel Analysis
// Onboarding funnel stages:
//   signup → first_login → workspace_created →
//   first_project → invited_teammate
//
// Calculate:
//   - Users who reached each step
//   - Drop-off rate at each step
//   - Median time between steps (in minutes)
// ============================================================

// Run on: nimbus_events.onboarding_events
db.onboarding_events.aggregate([

  // Step 1: Get each user's timestamp per step
  {
    $group: {
      _id: {
        member_id:   "$member_id",
        customer_id: "$customer_id",
        step:        "$step"
      },
      step_time: { $min: { $toDate: "$timestamp" } },
      completed: { $max: "$completed" }
    }
  },

  // Step 2: Group all steps per user into one document
  {
    $group: {
      _id: "$_id.member_id",
      customer_id: { $first: "$_id.customer_id" },
      steps: {
        $push: {
          step:      "$_id.step",
          step_time: "$step_time",
          completed: "$completed"
        }
      }
    }
  },

  // Step 3: Extract timestamps for each funnel step
  {
    $addFields: {
      t_signup: {
        $arrayElemAt: [
          {
            $map: {
              input: {
                $filter: {
                  input: "$steps", as: "s",
                  cond: { $eq: ["$$s.step", "signup"] }
                }
              },
              as: "s", in: "$$s.step_time"
            }
          }, 0
        ]
      },
      t_first_login: {
        $arrayElemAt: [
          {
            $map: {
              input: {
                $filter: {
                  input: "$steps", as: "s",
                  cond: { $eq: ["$$s.step", "first_login"] }
                }
              },
              as: "s", in: "$$s.step_time"
            }
          }, 0
        ]
      },
      t_workspace: {
        $arrayElemAt: [
          {
            $map: {
              input: {
                $filter: {
                  input: "$steps", as: "s",
                  cond: { $eq: ["$$s.step", "workspace_created"] }
                }
              },
              as: "s", in: "$$s.step_time"
            }
          }, 0
        ]
      },
      t_first_project: {
        $arrayElemAt: [
          {
            $map: {
              input: {
                $filter: {
                  input: "$steps", as: "s",
                  cond: { $eq: ["$$s.step", "first_project"] }
                }
              },
              as: "s", in: "$$s.step_time"
            }
          }, 0
        ]
      },
      t_invited: {
        $arrayElemAt: [
          {
            $map: {
              input: {
                $filter: {
                  input: "$steps", as: "s",
                  cond: { $eq: ["$$s.step", "invited_teammate"] }
                }
              },
              as: "s", in: "$$s.step_time"
            }
          }, 0
        ]
      }
    }
  },

  // Step 4: Flag which steps each user completed
  {
    $addFields: {
      did_signup:          { $cond: [{ $ifNull: ["$t_signup",       false] }, 1, 0] },
      did_first_login:     { $cond: [{ $ifNull: ["$t_first_login",  false] }, 1, 0] },
      did_workspace:       { $cond: [{ $ifNull: ["$t_workspace",    false] }, 1, 0] },
      did_first_project:   { $cond: [{ $ifNull: ["$t_first_project",false] }, 1, 0] },
      did_invited:         { $cond: [{ $ifNull: ["$t_invited",      false] }, 1, 0] },

      // Time between steps in minutes
      mins_signup_to_login: {
        $cond: [
          { $and: [{ $ifNull: ["$t_signup", false] }, { $ifNull: ["$t_first_login", false] }] },
          { $divide: [{ $subtract: ["$t_first_login", "$t_signup"] }, 60000] },
          null
        ]
      },
      mins_login_to_workspace: {
        $cond: [
          { $and: [{ $ifNull: ["$t_first_login", false] }, { $ifNull: ["$t_workspace", false] }] },
          { $divide: [{ $subtract: ["$t_workspace", "$t_first_login"] }, 60000] },
          null
        ]
      },
      mins_workspace_to_project: {
        $cond: [
          { $and: [{ $ifNull: ["$t_workspace", false] }, { $ifNull: ["$t_first_project", false] }] },
          { $divide: [{ $subtract: ["$t_first_project", "$t_workspace"] }, 60000] },
          null
        ]
      },
      mins_project_to_invite: {
        $cond: [
          { $and: [{ $ifNull: ["$t_first_project", false] }, { $ifNull: ["$t_invited", false] }] },
          { $divide: [{ $subtract: ["$t_invited", "$t_first_project"] }, 60000] },
          null
        ]
      }
    }
  },

  // Step 5: Aggregate funnel counts across all users
  {
    $group: {
      _id: null,
      total_users:            { $sum: 1 },
      reached_signup:         { $sum: "$did_signup" },
      reached_first_login:    { $sum: "$did_first_login" },
      reached_workspace:      { $sum: "$did_workspace" },
      reached_first_project:  { $sum: "$did_first_project" },
      reached_invited:        { $sum: "$did_invited" },

      // Collect times for median calculation
      times_signup_to_login:        { $push: "$mins_signup_to_login" },
      times_login_to_workspace:     { $push: "$mins_login_to_workspace" },
      times_workspace_to_project:   { $push: "$mins_workspace_to_project" },
      times_project_to_invite:      { $push: "$mins_project_to_invite" }
    }
  },

  // Step 6: Calculate drop-off rates
  {
    $addFields: {
      dropoff_signup_to_login: {
        $round: [
          {
            $multiply: [
              {
                $subtract: [
                  1,
                  { $divide: ["$reached_first_login", { $max: ["$reached_signup", 1] }] }
                ]
              },
              100
            ]
          }, 2
        ]
      },
      dropoff_login_to_workspace: {
        $round: [
          {
            $multiply: [
              {
                $subtract: [
                  1,
                  { $divide: ["$reached_workspace", { $max: ["$reached_first_login", 1] }] }
                ]
              },
              100
            ]
          }, 2
        ]
      },
      dropoff_workspace_to_project: {
        $round: [
          {
            $multiply: [
              {
                $subtract: [
                  1,
                  { $divide: ["$reached_first_project", { $max: ["$reached_workspace", 1] }] }
                ]
              },
              100
            ]
          }, 2
        ]
      },
      dropoff_project_to_invite: {
        $round: [
          {
            $multiply: [
              {
                $subtract: [
                  1,
                  { $divide: ["$reached_invited", { $max: ["$reached_first_project", 1] }] }
                ]
              },
              100
            ]
          }, 2
        ]
      }
    }
  },

  // Step 7: Clean output
  {
    $project: {
      _id:                          0,
      total_users:                  1,
      reached_signup:               1,
      reached_first_login:          1,
      reached_workspace_created:    "$reached_workspace",
      reached_first_project:        1,
      reached_invited_teammate:     "$reached_invited",
      dropoff_signup_to_login_pct:        "$dropoff_signup_to_login",
      dropoff_login_to_workspace_pct:     "$dropoff_login_to_workspace",
      dropoff_workspace_to_project_pct:   "$dropoff_workspace_to_project",
      dropoff_project_to_invite_pct:      "$dropoff_project_to_invite"
    }
  }
])


// ============================================================
// Q4: Cross-Reference — Top 20 Upsell Targets
// Find the most engaged users who are on the FREE tier.
// Cross-reference customer_ids from SQL (free tier) with
// MongoDB activity data.
//
// Engagement Score Formula (justified below):
//   score = (total_events * 0.4)          -- breadth of activity
//         + (unique_days_active * 0.3)    -- consistency/habit
//         + (avg_session_duration * 0.2)  -- depth per session
//         + (unique_features_used * 0.1)  -- feature exploration
//
// Rationale:
//   - Total events shows overall platform usage
//   - Unique days active shows they keep coming back (sticky)
//   - Avg session duration shows they're not just clicking once
//   - Unique features used shows they're exploring — upgrade candidates
// ============================================================

// STEP A: First get free-tier customer_ids from PostgreSQL.
// Run this SQL query in pgAdmin and note the customer_ids:
//
//   SELECT c.customer_id
//   FROM nimbus.customers c
//   JOIN nimbus.subscriptions s ON s.customer_id = c.customer_id
//   JOIN nimbus.plans p ON p.plan_id = s.plan_id
//   WHERE LOWER(p.plan_tier) = 'free'
//   AND s.status = 'active';
//
// Then replace the array below with actual IDs from that query.
// Example shown with placeholder IDs:

// Run on: nimbus_events.user_activity_logs
db.user_activity_logs.aggregate([

  // Step 1: Filter to free-tier customers only
  // Replace this array with actual free-tier customer_ids from SQL
  {
    $match: {
      customer_id: {
        $in: [
          // Paste your free-tier customer_ids here from the SQL query above
          // Example: 101, 203, 305, 412 ...
          // To get them run in pgAdmin:
          // SELECT customer_id FROM nimbus.customers c
          // JOIN nimbus.subscriptions s USING (customer_id)
          // JOIN nimbus.plans p USING (plan_id)
          // WHERE LOWER(p.plan_tier) = 'free' AND s.status = 'active'
        ]
      }
    }
  },

  // Step 2: Compute engagement metrics per user
  {
    $group: {
      _id: {
        member_id:   "$member_id",
        customer_id: "$customer_id"
      },
      total_events: { $sum: 1 },
      unique_days_active: {
        $addToSet: {
          $dateToString: {
            format: "%Y-%m-%d",
            date:   { $toDate: "$timestamp" }
          }
        }
      },
      total_session_duration: { $sum: "$session_duration_sec" },
      unique_features: { $addToSet: "$event_type" }
    }
  },

  // Step 3: Calculate derived metrics
  {
    $addFields: {
      unique_days_count:    { $size: "$unique_days_active" },
      unique_features_count: { $size: "$unique_features" },
      avg_session_duration: {
        $divide: ["$total_session_duration", { $max: ["$total_events", 1] }]
      }
    }
  },

  // Step 4: Calculate engagement score
  // Score = events(40%) + days(30%) + avg_duration(20%) + features(10%)
  // Normalize avg_duration by dividing by 60 to bring to similar scale
  {
    $addFields: {
      engagement_score: {
        $round: [
          {
            $add: [
              { $multiply: ["$total_events",         0.4] },
              { $multiply: ["$unique_days_count",    0.3] },
              { $multiply: [
                  { $divide: ["$avg_session_duration", 60] }, 0.2
                ]
              },
              { $multiply: ["$unique_features_count", 0.1] }
            ]
          },
          2
        ]
      }
    }
  },

  // Step 5: Sort by score and take top 20
  { $sort: { engagement_score: -1 } },
  { $limit: 20 },

  // Step 6: Clean output
  {
    $project: {
      _id:                   0,
      member_id:             "$_id.member_id",
      customer_id:           "$_id.customer_id",
      total_events:          1,
      unique_days_active:    "$unique_days_count",
      unique_features_used:  "$unique_features_count",
      avg_session_duration_sec: { $round: ["$avg_session_duration", 0] },
      engagement_score:      1
    }
  }
])